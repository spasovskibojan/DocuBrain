import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, rate_limit
from app.core.redis_client import redis_client
from app.models.query_history import QueryHistory
from app.models.user import User
from app.schemas.query import QueryRequest, QueryResponse
from app.services.rag_pipeline import rag_app

router = APIRouter()

@router.post("/ask", response_model=QueryResponse, dependencies=[Depends(rate_limit)])
async def ask_question(
    request: QueryRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """
    Executes the LangGraph RAG pipeline to answer a user's question based on their uploaded documents.
    """
    collection_name = f"user_{current_user.id.hex}_docs"
    user_key = current_user.id.hex
    document_scope = str(request.document_id) if request.document_id else None

    cached = await redis_client.get_cached_query(request.question, user_key, document_scope)
    if cached:
        db_query = QueryHistory(
            user_id=current_user.id,
            question=request.question,
            answer=cached["answer"],
            source_chunks=cached["sources"],
            from_cache=True
        )
        db.add(db_query)
        await db.commit()
        await db.refresh(db_query)
        return QueryResponse(
            answer=cached["answer"],
            sources=cached["sources"],
            from_cache=True,
            query_id=db_query.id
        )
    
    initial_state = {
        "question": request.question,
        "collection_name": collection_name,
        "document_id": str(request.document_id) if request.document_id else None
    }
    
    try:
        final_state = await rag_app.ainvoke(initial_state)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Pipeline failed: {str(e)}")
        
    answer = final_state["answer"]
    best_chunks = final_state["reranked_docs"]
    
    sources_data = [
        {
            "document_id": str(doc["payload"]["document_id"]),
            "document_name": doc["payload"].get("filename", "Uploaded Document"),
            "page_number": doc["payload"].get("page_number", 1),
            "chunk_text": doc["payload"]["text"],
            "relevance_score": doc["relevance_score"]
        } 
        for doc in best_chunks
    ]

    await redis_client.set_cached_query(
        request.question, user_key, {"answer": answer, "sources": sources_data}, document_scope
    )
    
    db_query = QueryHistory(
        user_id=current_user.id,
        question=request.question,
        answer=answer,
        source_chunks=sources_data
    )
    db.add(db_query)
    await db.commit()
    await db.refresh(db_query)
    
    return QueryResponse(
        answer=answer,
        sources=sources_data,
        from_cache=False,
        query_id=db_query.id
    )

from app.schemas.query import QueryHistoryResponse

@router.get("/history", response_model=list[QueryHistoryResponse])
async def get_query_history(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Retrieve the user's past chat questions and answers."""
    from sqlalchemy import select
    from app.schemas.query import QueryHistoryResponse
    
    result = await db.execute(
        select(QueryHistory)
        .where(QueryHistory.user_id == current_user.id)
        .order_by(QueryHistory.created_at.desc())
        .limit(10)
    )
    # Reverse so they are chronologically ordered for the UI
    history = result.scalars().all()
    return history[::-1]

@router.delete("/history", status_code=204)
async def clear_query_history(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Deletes all chat history for the current user."""
    from sqlalchemy import delete
    await db.execute(
        delete(QueryHistory)
        .where(QueryHistory.user_id == current_user.id)
    )
    await db.commit()
    return None

