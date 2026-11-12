import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, rate_limit
from app.core.tracing import model_metadata, trace_request
from app.models.document import Document
from app.models.user import User
from app.schemas.workflow import InvoiceData
from app.services.qdrant_service import qdrant_client
from qdrant_client.http import models

from langchain_groq import ChatGroq
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(rate_limit)])

EXTRACTION_ATTEMPTS = 2

# Groq free tier is 6000 TPM
INVOICE_CHUNKS = 12
BRIEF_CHUNKS = 16
DIFF_CHUNKS = 8

llm = ChatGroq(
    model=settings.GROQ_ANSWER_MODEL,
    api_key=settings.GROQ_API_KEY,
    temperature=0.0,
    model_kwargs={"reasoning_effort": "low"}
).with_config(**model_metadata(settings.GROQ_ANSWER_MODEL))


def _chunk_indexes(total: int | None, limit: int, edges_only: bool = False) -> list[int]:
    # Invoices keep the vendor at the top and the totals at the bottom, other documents are sampled evenly
    if not total or total <= limit:
        return list(range(total or limit))
    if edges_only:
        head = limit // 2
        return list(range(head)) + list(range(total - (limit - head), total))
    return [i * total // limit for i in range(limit)]


def _chunks_filter(document_id: uuid.UUID, indexes: list[int]) -> models.Filter:
    return models.Filter(
        must=[
            models.FieldCondition(key="document_id", match=models.MatchValue(value=str(document_id))),
            models.FieldCondition(key="chunk_index", match=models.MatchAny(any=indexes)),
        ]
    )


def _join_chunks(points) -> str:
    # Scroll returns points in ID order and the IDs are random
    points.sort(key=lambda p: p.payload.get("chunk_index", 0))
    parts = []
    previous = None
    for p in points:
        index = p.payload.get("chunk_index", 0)
        if previous is not None and index > previous + 1:
            parts.append("[...]")
        parts.append(p.payload.get("text", ""))
        previous = index
    return "\n\n".join(parts)

@router.post("/extract-invoice", response_model=InvoiceData)
async def extract_invoice(
    document_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Extract vendor, date, total and tax from an invoice as JSON."""
    _, full_text = await _get_doc_text(db, current_user.id, document_id, INVOICE_CHUNKS, edges_only=True)

    system_prompt = """You are an expert accounting AI. Your job is to extract data from the provided invoice text.
            You MUST respond with valid JSON only. Do not include markdown code blocks or explanations.

            Use this exact JSON schema:
            {
                "vendor_name": "string or null",
                "invoice_date": "string or null",
                "total_amount": "string or null",
                "tax_amount": "string or null"
            }"""

    messages = [
        ("system", system_prompt),
        ("human", f"Extract data from this invoice:\n\n{full_text}")
    ]
    json_llm = llm.bind(response_format={"type": "json_object"})

    with trace_request("extract-invoice", current_user.id.hex, {"document_id": str(document_id)}) as trace:
        for attempt in range(1, EXTRACTION_ATTEMPTS + 1):
            try:
                response = await json_llm.ainvoke(messages, config=trace.config)
            except Exception:
                logger.exception("Invoice extraction call failed (attempt %d)", attempt)
                continue

            try:
                invoice = InvoiceData.model_validate_json(response.content)
                trace.set_output(invoice.model_dump())
                return invoice
            except ValidationError as e:
                logger.warning("Invoice extraction returned invalid data (attempt %d): %s", attempt, e)
                messages = [
                    *messages,
                    ("ai", response.content),
                    ("human", f"That did not match the schema:\n{e}\nReturn only the corrected JSON object."),
                ]

    raise HTTPException(status_code=502, detail="AI failed to return valid structured data.")

async def _get_doc_text(
    db: AsyncSession, user_id: uuid.UUID, document_id: uuid.UUID, limit: int, edges_only: bool = False
) -> tuple[str, str]:
    result = await db.execute(select(Document).where(Document.id == document_id).where(Document.user_id == user_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found")

    indexes = _chunk_indexes(doc.chunk_count, limit, edges_only)
    try:
        points, _ = await qdrant_client.scroll(
            collection_name=doc.qdrant_collection,
            scroll_filter=_chunks_filter(doc.id, indexes),
            limit=len(indexes),
            with_payload=True,
            with_vectors=False
        )
    except Exception:
        logger.exception("Failed to read chunks of document %s", doc.id)
        raise HTTPException(status_code=500, detail="Failed to read document chunks.")

    if not points:
        raise HTTPException(status_code=400, detail="No text found in document")
    return doc.filename, _join_chunks(points)

@router.post("/executive-brief")
async def executive_brief(
    document_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    _, full_text = await _get_doc_text(db, current_user.id, document_id, BRIEF_CHUNKS)
    system_prompt = "You are an expert financial analyst. Read the following document excerpt and provide a highly professional, 3-bullet point executive summary. Focus only on the most critical information. Use markdown formatting. "
    system_prompt += "Respond in English."
    
    try:
        with trace_request("summarize-document", current_user.id.hex, {"document_id": str(document_id)}) as trace:
            response = await llm.ainvoke([("system", system_prompt), ("human", full_text)], config=trace.config)
            trace.set_output(response.content)
        return {"brief": response.content}
    except Exception:
        logger.exception("Executive brief failed for document %s", document_id)
        raise HTTPException(status_code=500, detail="Failed to generate brief.")

@router.post("/contract-diff")
async def contract_diff(
    doc1_id: uuid.UUID,
    doc2_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    if doc1_id == doc2_id:
        raise HTTPException(status_code=400, detail="Select two different documents.")

    name1, text1 = await _get_doc_text(db, current_user.id, doc1_id, DIFF_CHUNKS)
    name2, text2 = await _get_doc_text(db, current_user.id, doc2_id, DIFF_CHUNKS)

    system_prompt = "You are an expert legal auditor. Compare the two document excerpts below. Identify exactly what has changed between the first and the second document. Provide a clear markdown list of the differences. "
    system_prompt += "Refer to each document by its file name as plain text, never as 'Document 1' or 'Document 2'. "
    system_prompt += "Respond in English."
    human_prompt = f"### {name1}:\n{text1}\n\n### {name2}:\n{text2}"
    
    try:
        with trace_request("compare-contracts", current_user.id.hex, {"documents": [name1, name2]}) as trace:
            response = await llm.ainvoke([("system", system_prompt), ("human", human_prompt)], config=trace.config)
            trace.set_output(response.content)
        return {"diff": response.content}
    except Exception:
        logger.exception("Contract diff failed for documents %s and %s", doc1_id, doc2_id)
        raise HTTPException(status_code=500, detail="Failed to compare contracts.")
