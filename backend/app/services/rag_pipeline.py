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


async def retrieve_node(state: GraphState):
    question = state["question"]
    
    question_vector = generate_embeddings([question])[0]
    
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

    search_result = await qdrant_client.search(
        collection_name=state["collection_name"],
        query_vector=question_vector,
        query_filter=filter_params,
        limit=settings.TOP_K_RETRIEVAL,
    )
    
    docs = [{"payload": p.payload, "score": p.score} for p in search_result]
    return {"retrieved_docs": docs}


async def rerank_node(state: GraphState):
    question = state["question"]
    docs = state["retrieved_docs"]
    
    best_docs = rerank_documents(question, docs, top_k=settings.TOP_K_RERANK)
    return {"reranked_docs": best_docs}


async def generate_node(state: GraphState):
    question = state["question"]
    docs = state["reranked_docs"]
    
    context_text = "\n\n---\n\n".join([d["payload"]["text"] for d in docs])
    
    prompt = ChatPromptTemplate.from_template(
        "You are an expert AI assistant for an accounting firm. "
        "Use the following pieces of retrieved context from the firm's documents to answer the question. "
        "If you don't know the answer based on the context, just say that you don't know. Do not hallucinate.\n\n"
        "Context: {context}\n\n"
        "Question: {question}\n\n"
        "Answer:"
    )
    
    llm = ChatGroq(
        model=settings.GROQ_MODEL,
        groq_api_key=settings.GROQ_API_KEY,
        temperature=0.0,
        model_kwargs={"reasoning_effort": "low"}
    )
    
    chain = prompt | llm
    response = await chain.ainvoke({"context": context_text, "question": question})
    
    return {"answer": response.content}


workflow = StateGraph(GraphState)

workflow.add_node("retrieve", retrieve_node)
workflow.add_node("rerank", rerank_node)
workflow.add_node("generate", generate_node)

workflow.set_entry_point("retrieve")
workflow.add_edge("retrieve", "rerank")
workflow.add_edge("rerank", "generate")
workflow.add_edge("generate", END)

rag_app = workflow.compile()
