from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from qdrant_client.http import models

from app.core.config import settings
from app.services import rag_pipeline
from app.services.rag_pipeline import generate_node, retrieve_node, route_after_rerank


def _chunk(document_id: str, index: int, text: str, score: float = 0.0) -> dict:
    return {
        "payload": {"document_id": document_id, "chunk_index": index, "text": text},
        "relevance_score": score,
    }


def test_route_generates_when_score_passes_threshold():
    state = {"reranked_docs": [_chunk("a", 0, "x", settings.RELEVANCE_THRESHOLD + 1)], "rewrite_attempts": 0}
    assert route_after_rerank(state) == "generate"


def test_route_rewrites_low_score_once():
    state = {"reranked_docs": [_chunk("a", 0, "x", settings.RELEVANCE_THRESHOLD - 5)], "rewrite_attempts": 0}
    assert route_after_rerank(state) == "rewrite_query"


def test_route_falls_back_to_generate_after_rewrites():
    state = {
        "reranked_docs": [_chunk("a", 0, "x", settings.RELEVANCE_THRESHOLD - 5)],
        "rewrite_attempts": settings.MAX_QUERY_REWRITES,
    }
    assert route_after_rerank(state) == "generate"


def test_route_returns_no_answer_without_chunks():
    state = {"reranked_docs": [], "rewrite_attempts": 0}
    assert route_after_rerank(state) == "no_answer"


@pytest.mark.asyncio
async def test_generate_keeps_document_chunks_together_and_in_order(monkeypatch):
    captured = {}

    def fake_llm(prompt_value):
        captured["prompt"] = prompt_value.to_string()
        return AIMessage(content="ok")

    monkeypatch.setattr(rag_pipeline, "ChatGroq", lambda **kwargs: RunnableLambda(fake_llm))

    docs = [
        _chunk("inv-1", 1, "INV1-TOTAL 80.181,00"),
        _chunk("inv-2", 1, "INV2-TOTAL 48.616,00"),
        _chunk("inv-1", 0, "INV1-HEADER KP-118"),
        _chunk("inv-2", 0, "INV2-HEADER OS-0147"),
    ]
    result = await generate_node({"question": "Totals?", "reranked_docs": docs})

    assert result["answer"] == "ok"
    context = captured["prompt"].split("Context:", 1)[1].split("Question:", 1)[0]
    sections = context.split("===== NEXT DOCUMENT =====")
    assert len(sections) == 2
    first, second = sections
    assert first.index("INV1-HEADER") < first.index("INV1-TOTAL")
    assert "INV2" not in first
    assert second.index("INV2-HEADER") < second.index("INV2-TOTAL")
    # Passage numbers follow the reranked order, which is also the order of the returned sources
    assert "[3] INV1-HEADER" in first and "[1] INV1-TOTAL" in first
    assert "[4] INV2-HEADER" in second and "[2] INV2-TOTAL" in second


def test_model_specific_citation_markers_are_normalized():
    assert rag_pipeline._normalize_citations("Total is $5【1】【3†L2-L4】.") == "Total is $5[1][3]."


@pytest.mark.asyncio
async def test_retrieve_fuses_dense_and_bm25_search(monkeypatch):
    captured = {}

    class FakeQdrant:
        async def collection_exists(self, name):
            return True

        async def query_points(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(points=[SimpleNamespace(payload={"text": "x"}, score=0.5)])

    monkeypatch.setattr(rag_pipeline, "qdrant_client", FakeQdrant())
    monkeypatch.setattr(rag_pipeline, "generate_embeddings", lambda texts: [[0.1, 0.2]])

    result = await retrieve_node({"question": "INV-0042 total", "collection_name": "c", "document_id": "doc-1"})

    assert result["retrieved_docs"] == [{"payload": {"text": "x"}, "score": 0.5}]
    dense, sparse = captured["prefetch"]
    assert (dense.using, sparse.using) == ("dense", "bm25")
    assert sparse.query.text == "INV-0042 total"
    assert dense.filter.must[0].match.value == "doc-1" and sparse.filter == dense.filter
    assert captured["query"].fusion == models.Fusion.RRF


@pytest.mark.asyncio
async def test_retrieve_returns_nothing_when_user_has_no_collection(monkeypatch):
    class NoCollection:
        async def collection_exists(self, name):
            return False

    def embeddings_must_not_run(texts):
        raise AssertionError("nothing to search, the question should not be embedded")

    monkeypatch.setattr(rag_pipeline, "qdrant_client", NoCollection())
    monkeypatch.setattr(rag_pipeline, "generate_embeddings", embeddings_must_not_run)

    result = await retrieve_node({"question": "Total?", "collection_name": "user_x_docs", "document_id": None})

    assert result == {"retrieved_docs": []}
