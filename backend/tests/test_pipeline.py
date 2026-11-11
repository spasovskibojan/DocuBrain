import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from app.core.config import settings
from app.services import rag_pipeline
from app.services.rag_pipeline import generate_node, route_after_rerank


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
    state = {"reranked_docs": [], "rewrite_attempts": settings.MAX_QUERY_REWRITES}
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
    result = await generate_node({"question": "Totals?", "reranked_docs": docs, "language": "English"})

    assert result["answer"] == "ok"
    context = captured["prompt"].split("Context:", 1)[1].split("Question:", 1)[0]
    sections = context.split("===== NEXT DOCUMENT =====")
    assert len(sections) == 2
    first, second = sections
    assert first.index("INV1-HEADER") < first.index("INV1-TOTAL")
    assert "INV2" not in first
    assert second.index("INV2-HEADER") < second.index("INV2-TOTAL")
