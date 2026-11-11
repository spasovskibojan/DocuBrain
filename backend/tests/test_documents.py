import uuid

import pytest

from app.api import documents as documents_api

pytestmark = pytest.mark.asyncio

PASSWORD = "Str0ngPassw0rd"


def _make_pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
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

    async def fake_upsert(collection_name, document_id, chunks, embeddings, filename=None):
        stored[str(document_id)] = {"collection": collection_name, "chunks": chunks, "filename": filename}

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


async def test_upload_rejects_non_pdf(client, fake_vector_store):
    headers = await _auth_headers(client)
    files = {"file": ("notes.txt", b"hello", "text/plain")}
    response = await client.post("/api/documents/upload", files=files, headers=headers)
    assert response.status_code == 400


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
