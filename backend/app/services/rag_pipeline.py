import asyncio
import json
import re
from typing import TypedDict, List
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig, RunnableLambda
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, END

from app.core.config import settings
from app.core.tracing import model_metadata
from app.services.embeddings import generate_embeddings
from qdrant_client.http import models

from app.services.qdrant_service import DENSE_VECTOR, SPARSE_VECTOR, bm25, qdrant_client
from app.services.reranker import rerank_documents


class GraphState(TypedDict):
    question: str
    collection_name: str
    document_id: str | None
    retrieved_docs: List[dict]
    reranked_docs: List[dict]
    answer: str
    search_query: str
    rewrite_attempts: int


async def _hybrid_search(inputs: dict) -> List[dict]:
    question_vector = (await asyncio.to_thread(generate_embeddings, [inputs["query"]]))[0]

    filter_params = None
    if inputs["document_id"]:
        filter_params = models.Filter(
            must=[
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchValue(value=inputs["document_id"])
                )
            ]
        )

    prefetch = [models.Prefetch(query=question_vector, using=DENSE_VECTOR, filter=filter_params, limit=settings.TOP_K_RETRIEVAL)]
    if settings.HYBRID_SEARCH:
        prefetch.append(models.Prefetch(query=bm25(inputs["query"]), using=SPARSE_VECTOR, filter=filter_params, limit=settings.TOP_K_RETRIEVAL))

    # Dense search matches meaning, BM25 matches exact terms such as invoice numbers; RRF merges both rankings
    search_result = await qdrant_client.query_points(
        collection_name=inputs["collection_name"],
        prefetch=prefetch,
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=settings.TOP_K_RETRIEVAL,
    )
    return [{"payload": p.payload, "score": p.score} for p in search_result.points]


async def retrieve_node(state: GraphState, config: RunnableConfig | None = None):
    question = state.get("search_query") or state["question"]

    # A user who has not uploaded anything yet has no collection
    if not await qdrant_client.collection_exists(state["collection_name"]):
        return {"retrieved_docs": []}

    # Invoked as a runnable so the search is traced as its own step under "retrieve"
    docs = await RunnableLambda(_hybrid_search).with_config(run_name="hybrid-search").ainvoke(
        {"query": question, "collection_name": state["collection_name"], "document_id": state["document_id"]},
        config=config,
    )
    return {"retrieved_docs": docs}


async def rerank_node(state: GraphState):
    question = state.get("search_query") or state["question"]
    docs = state["retrieved_docs"]
    
    best_docs = await asyncio.to_thread(rerank_documents, question, docs, top_k=settings.TOP_K_RERANK)
    return {"reranked_docs": best_docs}


def _normalize_citations(answer: str) -> str:
    # gpt-oss sometimes cites as 【1】 or 【1†source】 instead of [1]
    return re.sub(r"【(\d+)[^】]*】", lambda m: f"[{m.group(1)}]", answer)


async def condense_question(question: str, history: List[dict], config: dict | None = None) -> tuple[str, bool]:
    if not history:
        return question, False

    conversation = "\n".join(f"User: {h['question']}\nAssistant: {h['answer'][:500]}" for h in history)
    prompt = ChatPromptTemplate.from_template(
        "Classify the latest user message in this conversation about the user's documents.\n"
        '- "reformat": it only asks to repeat, shorten or reformat the previous answer.\n'
        '- "question": it asks something new. Rewrite it as a standalone question, resolving references '
        "to earlier messages.\n"
        'Return only JSON: {{"type": "reformat" or "question", "question": "..."}}\n\n'
        "Conversation:\n{conversation}\n\n"
        "Latest message: {question}"
    )

    llm = ChatGroq(
        model=settings.GROQ_MODEL,
        groq_api_key=settings.GROQ_API_KEY,
        temperature=0.0,
        model_kwargs={"reasoning_effort": "low"}
    ).with_config(**model_metadata(settings.GROQ_MODEL))

    try:
        response = await (prompt | llm).with_config(run_name="condense-question").ainvoke({"conversation": conversation, "question": question}, config=config)
        content = response.content.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
        data = json.loads(content)
    except Exception:
        return question, False

    if data.get("type") == "reformat":
        return question, True
    return data.get("question") or question, False


async def reformat_answer(previous_answer: str, request: str, config: dict | None = None) -> str:
    prompt = ChatPromptTemplate.from_template(
        "Apply the user's request to the previous answer. Do not add any new facts. "
        "Keep citation markers such as [1] next to the statements they support. Respond in English.\n\n"
        "Previous answer:\n{previous_answer}\n\n"
        "User request: {request}"
    )

    llm = ChatGroq(
        model=settings.GROQ_MODEL,
        groq_api_key=settings.GROQ_API_KEY,
        temperature=0.0,
        model_kwargs={"reasoning_effort": "low"}
    ).with_config(**model_metadata(settings.GROQ_MODEL))

    response = await (prompt | llm).with_config(run_name="reformat-answer").ainvoke({"previous_answer": previous_answer, "request": request}, config=config)
    return _normalize_citations(response.content)


async def generate_node(state: GraphState):
    question = state["question"]
    docs = state["reranked_docs"]
    
    # Passages are numbered in the same order as the sources returned to the client
    grouped: dict[str, List[tuple[int, dict]]] = {}
    for number, d in enumerate(docs, start=1):
        grouped.setdefault(str(d["payload"]["document_id"]), []).append((number, d))
    sections = []
    for chunks in grouped.values():
        chunks.sort(key=lambda c: c[1]["payload"].get("chunk_index", 0))
        # Without the name, near-identical documents (two years of the same contract) get mixed up
        header = f"Document: {chunks[0][1]['payload'].get('filename', 'unknown')}\n"
        sections.append(header + "\n".join(f"[{number}] {c['payload']['text']}" for number, c in chunks))
    context_text = "\n\n===== NEXT DOCUMENT =====\n\n".join(sections)

    prompt = ChatPromptTemplate.from_template(
        "You are an expert AI assistant for an accounting firm. "
        "Use the following pieces of retrieved context from the firm's documents to answer the question. "
        "Documents are separated by '===== NEXT DOCUMENT ====='; never mix facts between documents. "
        "Answer only from the context, never from general knowledge. "
        "Use totals and amounts exactly as stated in the documents; do not recalculate them. "
        "If the context does not contain the answer, just say that you don't know. Do not hallucinate. "
        "Refer to the context as 'your documents', never as 'context' or 'retrieved context'. "
        "Each passage starts with its number in square brackets. After every statement, cite the passages "
        "it comes from, like [2] or [1][3]. Cite only these passage numbers, never section or clause "
        "numbers from the document text, such as 7.1. "
        "Respond in English.\n\n"
        "Context: {context}\n\n"
        "Question: {question}\n\n"
        "Answer:"
    )
    
    llm = ChatGroq(
        model=settings.GROQ_ANSWER_MODEL,
        groq_api_key=settings.GROQ_API_KEY,
        temperature=0.0,
        model_kwargs={"reasoning_effort": "low"}
    ).with_config(**model_metadata(settings.GROQ_ANSWER_MODEL))
    
    chain = (prompt | llm).with_config(run_name="generate-answer")
    response = await chain.ainvoke({"context": context_text, "question": question})
    
    return {"answer": _normalize_citations(response.content)}


async def rewrite_query_node(state: GraphState):
    prompt = ChatPromptTemplate.from_template(
        "Rewrite the following question so it works better as a search query over document chunks. "
        "Expand vague wording into specific terms. Return only the rewritten question.\n\n"
        "Question: {question}"
    )

    llm = ChatGroq(
        model=settings.GROQ_MODEL,
        groq_api_key=settings.GROQ_API_KEY,
        temperature=0.0,
        model_kwargs={"reasoning_effort": "low"}
    ).with_config(**model_metadata(settings.GROQ_MODEL))

    chain = (prompt | llm).with_config(run_name="rewrite-query")
    response = await chain.ainvoke({"question": state["question"]})

    return {
        "search_query": response.content.strip(),
        "rewrite_attempts": (state.get("rewrite_attempts") or 0) + 1,
    }


async def no_answer_node(state: GraphState):
    return {
        "answer": "I couldn't find this in your documents.",
        "reranked_docs": [],
    }


def route_after_rerank(state: GraphState):
    docs = state["reranked_docs"]
    # Vector search always returns its nearest chunks, so no chunks means there is nothing to search
    if not docs:
        return "no_answer"
    if docs[0]["relevance_score"] >= settings.RELEVANCE_THRESHOLD:
        return "generate"
    if (state.get("rewrite_attempts") or 0) < settings.MAX_QUERY_REWRITES:
        return "rewrite_query"
    return "generate"


workflow = StateGraph(GraphState)

workflow.add_node("retrieve", retrieve_node)
workflow.add_node("rerank", rerank_node)
workflow.add_node("generate", generate_node)
workflow.add_node("rewrite_query", rewrite_query_node)
workflow.add_node("no_answer", no_answer_node)

workflow.set_entry_point("retrieve")
workflow.add_edge("retrieve", "rerank")
workflow.add_conditional_edges(
    "rerank",
    route_after_rerank,
    {"generate": "generate", "rewrite_query": "rewrite_query", "no_answer": "no_answer"},
)
workflow.add_edge("rewrite_query", "retrieve")
workflow.add_edge("generate", END)
workflow.add_edge("no_answer", END)

rag_app = workflow.compile()
