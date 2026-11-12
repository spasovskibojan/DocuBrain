import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user, rate_limit
from app.core.redis_client import redis_client
from app.models.document import Document
from app.models.query_history import QueryHistory
from app.models.user import User
from app.schemas.query import QueryHistoryResponse, QueryRequest, QueryResponse
from app.services.rag_pipeline import condense_question, rag_app, reformat_answer

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/ask", response_model=QueryResponse, dependencies=[Depends(rate_limit)])
async def ask_question(
    request: QueryRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    collection_name = f"user_{current_user.id.hex}_docs"
    user_key = current_user.id.hex
    document_scope = str(request.document_id) if request.document_id else None

    if request.document_id:
        owned = await db.execute(
            select(Document.id)
            .where(Document.id == request.document_id)
            .where(Document.user_id == current_user.id)
        )
        if owned.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Document not found")

    recent = await db.execute(
        select(QueryHistory)
        .where(QueryHistory.user_id == current_user.id)
        .order_by(QueryHistory.created_at.desc())
        .limit(settings.CHAT_HISTORY_TURNS)
    )
    history_rows = list(reversed(recent.scalars().all()))
    history = [{"question": h.question, "answer": h.answer} for h in history_rows]
    question, language, is_reformat = await condense_question(request.question, history)

    if is_reformat:
        try:
            answer = await reformat_answer(history[-1]["answer"], request.question, language)
        except Exception:
            logger.exception("Reformatting the previous answer failed")
            raise HTTPException(status_code=500, detail="AI pipeline failed.")
        sources_data = history_rows[-1].source_chunks or []
        db_query = QueryHistory(
            user_id=current_user.id,
            document_id=request.document_id,
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

    cache_question = f"{language}:{question}"

    cached = await redis_client.get_cached_query(cache_question, user_key, document_scope)
    if cached:
        db_query = QueryHistory(
            user_id=current_user.id,
            document_id=request.document_id,
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
        "question": question,
        "language": language,
        "collection_name": collection_name,
        "document_id": str(request.document_id) if request.document_id else None
    }
    
    try:
        final_state = await rag_app.ainvoke(initial_state)
    except Exception:
        logger.exception("RAG pipeline failed")
        raise HTTPException(status_code=500, detail="AI pipeline failed.")
        
    answer = final_state["answer"]
    best_chunks = final_state["reranked_docs"]

    missing_ids = {doc["payload"]["document_id"] for doc in best_chunks if not doc["payload"].get("filename")}
    names = {}
    if missing_ids:
        rows = await db.execute(
            select(Document.id, Document.filename)
            .where(Document.id.in_(missing_ids))
            .where(Document.user_id == current_user.id)
        )
        names = {str(doc_id): name for doc_id, name in rows.all()}

    sources_data = [
        {
            "document_id": str(doc["payload"]["document_id"]),
            "document_name": doc["payload"].get("filename") or names.get(str(doc["payload"]["document_id"]), "Uploaded Document"),
            "page_number": doc["payload"].get("page_number") or 1,
            "chunk_text": doc["payload"]["text"],
            "relevance_score": doc["relevance_score"]
        } 
        for doc in best_chunks
    ]
    
    db_query = QueryHistory(
        user_id=current_user.id,
        document_id=request.document_id,
        question=request.question,
        answer=answer,
        source_chunks=sources_data
    )
    db.add(db_query)
    await db.commit()
    await db.refresh(db_query)

    await redis_client.set_cached_query(
        cache_question, user_key, {"answer": answer, "sources": sources_data}, document_scope
    )
    
    return QueryResponse(
        answer=answer,
        sources=sources_data,
        from_cache=False,
        query_id=db_query.id
    )

@router.get("/history", response_model=list[QueryHistoryResponse])
async def get_query_history(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Retrieve the user's past chat questions and answers."""
    result = await db.execute(
        select(QueryHistory)
        .where(QueryHistory.user_id == current_user.id)
        .order_by(QueryHistory.created_at.desc())
        .limit(10)
    )
    history = result.scalars().all()
    return history[::-1]

@router.delete("/history", status_code=204)
async def clear_query_history(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Deletes all chat history for the current user."""
    await db.execute(
        delete(QueryHistory)
        .where(QueryHistory.user_id == current_user.id)
    )
    await db.commit()
    return None

