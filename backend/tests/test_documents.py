import uuid
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from app.api import documents as documents_api
from app.api import workflows as workflows_api
from app.core.config import settings

pytestmark = pytest.mark.asyncio

PASSWORD = "Str0ngPassw0rd"


def _make_pdf(*page_texts: str) -> bytes:
    font_id = 3 + 2 * len(page_texts)
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(len(page_texts)))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {len(page_texts)} >>".encode(),
    ]
    for i, text in enumerate(page_texts):
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {4 + 2 * i} 0 R >>".encode()
        )
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    pdf = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(pdf)
    pdf += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    pdf += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    pdf += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return pdf


@pytest.fixture
def fake_vector_store(monkeypatch):
    stored = {}

    def fake_embeddings(chunks):
        return [[0.0] * 384 for _ in chunks]

    async def fake_upsert(collection_name, document_id, chunks, embeddings, filename=None, page_numbers=None):
        stored[str(document_id)] = {
            "collection": collection_name,
            "chunks": chunks,
            "filename": filename,
            "page_numbers": page_numbers,
        }

    async def fake_delete(collection_name, document_id):
        stored.pop(str(document_id), None)

    monkeypatch.setattr(documents_api, "generate_embeddings", fake_embeddings)
    monkeypatch.setattr(documents_api, "upsert_document_chunks", fake_upsert)
    monkeypatch.setattr(documents_api, "delete_document_chunks", fake_delete)
    return stored


async def _auth_headers(client) -> dict:
    email = f"user_{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
    login = await client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _upload(client, headers, name="invoice.pdf", text="Invoice total 1000 MKD"):
    files = {"file": (name, _make_pdf(text), "application/pdf")}
    return await client.post("/api/documents/upload", files=files, headers=headers)


async def test_upload_stores_chunks_and_lists_document(client, fake_vector_store):
    headers = await _auth_headers(client)

    response = await _upload(client, headers)
    assert response.status_code == 200
    doc = response.json()
    assert doc["is_processed"] is True
    assert doc["chunk_count"] >= 1

    stored = fake_vector_store[doc["id"]]
    assert stored["filename"] == "invoice.pdf"
    assert "Invoice total 1000 MKD" in " ".join(stored["chunks"])

    listing = await client.get("/api/documents/", headers=headers)
    assert [d["id"] for d in listing.json()["documents"]] == [doc["id"]]


async def test_upload_keeps_page_number_of_every_chunk(client, fake_vector_store):
    headers = await _auth_headers(client)
    files = {"file": ("contract.pdf", _make_pdf("First page terms", "Second page signatures"), "application/pdf")}

    response = await client.post("/api/documents/upload", files=files, headers=headers)
    assert response.status_code == 200
    doc = response.json()
    assert doc["page_count"] == 2

    stored = fake_vector_store[doc["id"]]
    pages = dict(zip(stored["chunks"], stored["page_numbers"]))
    assert pages == {"First page terms": 1, "Second page signatures": 2}


async def test_upload_rejects_non_pdf(client, fake_vector_store):
    headers = await _auth_headers(client)
    files = {"file": ("notes.txt", b"hello", "text/plain")}
    response = await client.post("/api/documents/upload", files=files, headers=headers)
    assert response.status_code == 400


async def test_upload_rejects_file_that_only_has_a_pdf_name(client, fake_vector_store):
    headers = await _auth_headers(client)
    files = {"file": ("fake.pdf", b"this is not a pdf", "application/pdf")}
    response = await client.post("/api/documents/upload", files=files, headers=headers)
    assert response.status_code == 400


async def test_upload_rejects_file_over_size_limit(client, fake_vector_store, monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 0)
    headers = await _auth_headers(client)
    response = await _upload(client, headers)
    assert response.status_code == 413


async def test_upload_without_extractable_text_is_rejected_and_not_stored(client, fake_vector_store):
    headers = await _auth_headers(client)
    response = await _upload(client, headers, text="")
    assert response.status_code == 422

    listing = await client.get("/api/documents/", headers=headers)
    assert listing.json()["documents"] == []


async def test_failed_processing_does_not_leak_internal_error(client, fake_vector_store, monkeypatch):
    def broken_embeddings(chunks):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(documents_api, "generate_embeddings", broken_embeddings)
    headers = await _auth_headers(client)
    response = await _upload(client, headers)
    assert response.status_code == 500
    assert "secret internal detail" not in response.text


async def test_users_cannot_access_each_others_documents(client, fake_vector_store):
    owner = await _auth_headers(client)
    other = await _auth_headers(client)
    doc_id = (await _upload(client, owner)).json()["id"]

    listing = await client.get("/api/documents/", headers=other)
    assert listing.json()["documents"] == []

    delete = await client.delete(f"/api/documents/{doc_id}", headers=other)
    assert delete.status_code == 404

    extract = await client.post(f"/api/workflows/extract-invoice?document_id={doc_id}", headers=other)
    assert extract.status_code == 404

    assert doc_id in fake_vector_store


async def test_owner_can_delete_document(client, fake_vector_store):
    headers = await _auth_headers(client)
    doc_id = (await _upload(client, headers)).json()["id"]

    delete = await client.delete(f"/api/documents/{doc_id}", headers=headers)
    assert delete.status_code == 204
    assert doc_id not in fake_vector_store

    listing = await client.get("/api/documents/", headers=headers)
    assert listing.json()["documents"] == []


class FakeLLM:
    def __init__(self, *replies: str):
        self.replies = list(replies)
        self.calls = 0

    def bind(self, **kwargs):
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        return AIMessage(content=self.replies.pop(0))


@pytest.fixture
def invoice_chunks(monkeypatch):
    captured = {}

    async def fake_scroll(collection_name, scroll_filter, limit, with_payload, with_vectors):
        captured["filter"] = scroll_filter
        points = [
            SimpleNamespace(payload={"chunk_index": 1, "text": "Total 1000 MKD"}),
            SimpleNamespace(payload={"chunk_index": 0, "text": "Vendor Acme"}),
        ]
        return points, None

    monkeypatch.setattr(workflows_api.qdrant_client, "scroll", fake_scroll)
    return captured


async def _extract(client, fake_vector_store, monkeypatch, llm):
    monkeypatch.setattr(workflows_api, "llm", llm)
    headers = await _auth_headers(client)
    doc_id = (await _upload(client, headers)).json()["id"]
    return await client.post(f"/api/workflows/extract-invoice?document_id={doc_id}", headers=headers)


async def test_extract_invoice_returns_validated_fields(client, fake_vector_store, invoice_chunks, monkeypatch):
    llm = FakeLLM('{"vendor_name": "Acme", "invoice_date": "2026-04-10", "total_amount": 1000, "tax_amount": null}')

    response = await _extract(client, fake_vector_store, monkeypatch, llm)

    assert response.status_code == 200
    assert response.json() == {
        "vendor_name": "Acme",
        "invoice_date": "2026-04-10",
        "total_amount": "1000",
        "tax_amount": None,
    }
    assert invoice_chunks["filter"].must[1].key == "chunk_index"
    assert invoice_chunks["filter"].must[1].range.lt == 10


async def test_extract_invoice_retries_after_invalid_output(client, fake_vector_store, invoice_chunks, monkeypatch):
    llm = FakeLLM(
        '{"vendor": "Acme"}',
        '{"vendor_name": "Acme", "invoice_date": null, "total_amount": "1000", "tax_amount": null}',
    )

    response = await _extract(client, fake_vector_store, monkeypatch, llm)

    assert response.status_code == 200
    assert response.json()["vendor_name"] == "Acme"
    assert llm.calls == 2


async def test_extract_invoice_gives_up_after_repeated_invalid_output(client, fake_vector_store, invoice_chunks, monkeypatch):
    llm = FakeLLM("not json", "still not json")

    response = await _extract(client, fake_vector_store, monkeypatch, llm)

    assert response.status_code == 502
    assert llm.calls == 2
