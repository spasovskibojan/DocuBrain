import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, rate_limit
from app.models.document import Document
from app.models.user import User
from app.services.qdrant_service import qdrant_client
from qdrant_client.http import models

from langchain_groq import ChatGroq
from app.core.config import settings

router = APIRouter(dependencies=[Depends(rate_limit)])

llm = ChatGroq(
    model=settings.GROQ_ANSWER_MODEL,
    api_key=settings.GROQ_API_KEY,
    temperature=0.0,
    model_kwargs={"reasoning_effort": "low"}
)


def _response_language(accept_language: str | None) -> str:
    return "Macedonian" if (accept_language or "").lower().startswith("mk") else "English"

@router.post("/extract-invoice")
async def extract_invoice(
    document_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Extract vendor, date, total and tax from an invoice as JSON."""
    result = await db.execute(
        select(Document)
        .where(Document.id == document_id)
        .where(Document.user_id == current_user.id)
    )
    doc = result.scalar_one_or_none()
    
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
        
    collection_name = doc.qdrant_collection
    try:
        points, _ = await qdrant_client.scroll(
            collection_name=collection_name,
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id",
                        match=models.MatchValue(value=str(doc.id))
                    )
                ]
            ),
            limit=10,  # Groq free tier is 6000 TPM
            with_payload=True,
            with_vectors=False
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read document chunks: {e}")

    if not points:
        raise HTTPException(status_code=400, detail="No text found in document")

    points.sort(key=lambda p: p.payload.get("chunk_index", 0))
    full_text = "\n\n".join([p.payload.get("text", "") for p in points])

    system_prompt = """You are an expert accounting AI. Your job is to extract data from the provided invoice text.
            You MUST respond with valid JSON only. Do not include markdown code blocks or explanations.

            Use this exact JSON schema:
            {
                "vendor_name": "string or null",
                "invoice_date": "string or null",
                "total_amount": "string or null",
                "tax_amount": "string or null"
            }"""

    try:
        messages = [
            ("system", system_prompt),
            ("human", f"Extract data from this invoice:\n\n{full_text}")
        ]
        
        response = await llm.ainvoke(messages)
        
        response_text = response.content.strip()
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
            
        data = json.loads(response_text)
        return data
        
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="AI failed to return valid structured data.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extraction failed: {str(e)}")

async def _get_doc_text(db: AsyncSession, user_id: uuid.UUID, document_id: uuid.UUID, limit: int = 10) -> str:
    result = await db.execute(select(Document).where(Document.id == document_id).where(Document.user_id == user_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found")
        
    try:
        points, _ = await qdrant_client.scroll(
            collection_name=doc.qdrant_collection,
            scroll_filter=models.Filter(must=[models.FieldCondition(key="document_id", match=models.MatchValue(value=str(doc.id)))]),
            limit=limit,
            with_payload=True,
            with_vectors=False
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read document chunks: {e}")

    if not points:
        raise HTTPException(status_code=400, detail="No text found in document")
    points.sort(key=lambda p: p.payload.get("chunk_index", 0))
    return "\n\n".join([p.payload.get("text", "") for p in points])

@router.post("/executive-brief")
async def executive_brief(
    document_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    accept_language: Annotated[str | None, Header()] = None
):
    full_text = await _get_doc_text(db, current_user.id, document_id, limit=8)
    system_prompt = "You are an expert financial analyst. Read the following document excerpt and provide a highly professional, 3-bullet point executive summary. Focus only on the most critical information. Use markdown formatting. "
    system_prompt += f"Respond in {_response_language(accept_language)}."
    
    try:
        response = await llm.ainvoke([("system", system_prompt), ("human", full_text)])
        return {"brief": response.content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate brief: {str(e)}")

@router.post("/contract-diff")
async def contract_diff(
    doc1_id: uuid.UUID,
    doc2_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    accept_language: Annotated[str | None, Header()] = None
):
    text1 = await _get_doc_text(db, current_user.id, doc1_id, limit=5)
    text2 = await _get_doc_text(db, current_user.id, doc2_id, limit=5)
    
    system_prompt = "You are an expert legal auditor. Compare the two document excerpts below. Identify exactly what has changed between Document 1 and Document 2. Provide a clear markdown list of the differences. "
    system_prompt += f"Respond in {_response_language(accept_language)}."
    human_prompt = f"### Document 1:\n{text1}\n\n### Document 2:\n{text2}"
    
    try:
        response = await llm.ainvoke([("system", system_prompt), ("human", human_prompt)])
        return {"diff": response.content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to compare contracts: {str(e)}")
