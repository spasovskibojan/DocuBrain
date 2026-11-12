import asyncio
import json
from typing import TypedDict, List
from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, END

from app.core.config import settings
from app.services.embeddings import generate_embeddings
from app.services.qdrant_service import qdrant_client
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
    language: str


async def retrieve_node(state: GraphState):
    question = state.get("search_query") or state["question"]

    # A user who has not uploaded anything yet has no collection
    if not await qdrant_client.collection_exists(state["collection_name"]):
        return {"retrieved_docs": []}

    question_vector = (await asyncio.to_thread(generate_embeddings, [question]))[0]

    filter_params = None
    if state["document_id"]:
        from qdrant_client.http import models
        filter_params = models.Filter(
            must=[
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchValue(value=state["document_id"])
                )
            ]
        )

    search_result = await qdrant_client.query_points(
        collection_name=state["collection_name"],
        query=question_vector,
        query_filter=filter_params,
        limit=settings.TOP_K_RETRIEVAL,
    )

    docs = [{"payload": p.payload, "score": p.score} for p in search_result.points]
    return {"retrieved_docs": docs}


async def rerank_node(state: GraphState):
    question = state.get("search_query") or state["question"]
    docs = state["retrieved_docs"]
    
    best_docs = await asyncio.to_thread(rerank_documents, question, docs, top_k=settings.TOP_K_RERANK)
    return {"reranked_docs": best_docs}


def _is_macedonian(text: str) -> bool:
    return any("\u0400" <= ch <= "\u04FF" for ch in text)


def _answer_language(state: GraphState) -> str:
    return state.get("language") or ("Macedonian" if _is_macedonian(state["question"]) else "English")


def _requested_language(message: str) -> str | None:
    text = message.lower()
    if "english" in text or "англиски" in text:
        return "English"
    if "macedonian" in text or "македонски" in text:
        return "Macedonian"
    return None


async def condense_question(question: str, history: List[dict]) -> tuple[str, str, bool]:
    language = _requested_language(question) or ("Macedonian" if _is_macedonian(question) else "English")
    if not history:
        return question, language, False

    conversation = "\n".join(f"User: {h['question']}\nAssistant: {h['answer'][:500]}" for h in history)
    prompt = ChatPromptTemplate.from_template(
        "Classify the latest user message in this conversation about the user's documents.\n"
        '- "reformat": it only asks to repeat, translate, shorten or reformat the previous answer.\n'
        '- "question": it asks something new. Rewrite it as a standalone question, resolving references '
        "to earlier messages, in the same language as the latest message.\n"
        'Return only JSON: {{"type": "reformat" or "question", "question": "..."}}\n\n'
        "Conversation:\n{conversation}\n\n"
        "Latest message: {question}"
    )

    llm = ChatGroq(
        model=settings.GROQ_MODEL,
        groq_api_key=settings.GROQ_API_KEY,
        temperature=0.0,
        model_kwargs={"reasoning_effort": "low"}
    )

    try:
        response = await (prompt | llm).ainvoke({"conversation": conversation, "question": question})
        content = response.content.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
        data = json.loads(content)
    except Exception:
        return question, language, False

    if data.get("type") == "reformat":
        if not _requested_language(question) and not _is_macedonian(question):
            language = "Macedonian" if _is_macedonian(history[-1]["answer"]) else "English"
        return question, language, True
    return data.get("question") or question, language, False


async def reformat_answer(previous_answer: str, request: str, language: str) -> str:
    prompt = ChatPromptTemplate.from_template(
        "Apply the user's request to the previous answer. Do not add any new facts. Respond in {language}.\n\n"
        "Previous answer:\n{previous_answer}\n\n"
        "User request: {request}"
    )

    llm = ChatGroq(
        model=settings.GROQ_MODEL,
        groq_api_key=settings.GROQ_API_KEY,
        temperature=0.0,
        model_kwargs={"reasoning_effort": "low"}
    )

    response = await (prompt | llm).ainvoke({"previous_answer": previous_answer, "request": request, "language": language})
    return response.content


async def generate_node(state: GraphState):
    question = state["question"]
    docs = state["reranked_docs"]
    
    grouped: dict[str, List[dict]] = {}
    for d in docs:
        grouped.setdefault(str(d["payload"]["document_id"]), []).append(d)
    sections = []
    for chunks in grouped.values():
        chunks.sort(key=lambda d: d["payload"].get("chunk_index", 0))
        sections.append("\n".join(c["payload"]["text"] for c in chunks))
    context_text = "\n\n===== NEXT DOCUMENT =====\n\n".join(sections)

    prompt = ChatPromptTemplate.from_template(
        "You are an expert AI assistant for an accounting firm. "
        "Use the following pieces of retrieved context from the firm's documents to answer the question. "
        "Documents are separated by '===== NEXT DOCUMENT ====='; never mix facts between documents. "
        "Answer only from the context, never from general knowledge. "
        "Use totals and amounts exactly as stated in the documents; do not recalculate them. "
        "If the context does not contain the answer, just say that you don't know. Do not hallucinate. "
        "Refer to the context as 'your documents', never as 'context' or 'retrieved context'. "
        "Respond in {language}.\n\n"
        "Context: {context}\n\n"
        "Question: {question}\n\n"
        "Answer:"
    )
    
    llm = ChatGroq(
        model=settings.GROQ_ANSWER_MODEL,
        groq_api_key=settings.GROQ_API_KEY,
        temperature=0.0,
        model_kwargs={"reasoning_effort": "low"}
    )
    
    chain = prompt | llm
    language = _answer_language(state)
    response = await chain.ainvoke({"context": context_text, "question": question, "language": language})
    
    return {"answer": response.content}


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
    )

    chain = prompt | llm
    response = await chain.ainvoke({"question": state["question"]})

    return {
        "search_query": response.content.strip(),
        "rewrite_attempts": (state.get("rewrite_attempts") or 0) + 1,
    }


async def no_answer_node(state: GraphState):
    return {
        "answer": "Не го најдов ова во вашите документи." if _answer_language(state) == "Macedonian" else "I couldn't find this in your documents.",
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
