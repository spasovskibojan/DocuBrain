import asyncio
import logging
import uuid
from typing import Annotated, List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.redis_client import redis_client
from app.models.document import Document
from app.models.user import User
from app.schemas.document import DocumentResponse, DocumentListResponse
from app.services.embeddings import generate_embeddings
from app.services.pdf_parser import chunk_pages, parse_pdf_pages, with_document_title
from app.services.qdrant_service import upsert_document_chunks, delete_document_chunks

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/upload", response_model=DocumentResponse)
async def upload_document(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...)
):
    """
    Uploads a PDF, extracts text, chunks it, embeds it, and stores it in Qdrant.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    if (file.size or 0) > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File is larger than {settings.MAX_UPLOAD_SIZE_MB} MB.",
        )

    file_bytes = await file.read()
    file_size = len(file_bytes)

    if b"%PDF-" not in file_bytes[:1024]:
        raise HTTPException(status_code=400, detail="The file is not a valid PDF.")

    collection_name = f"user_{current_user.id.hex}_docs"
    
    db_document = Document(
        user_id=current_user.id,
        filename=file.filename,
        file_size_bytes=file_size,
        qdrant_collection=collection_name,
        is_processed=False
    )
    db.add(db_document)
    await db.commit()
    await db.refresh(db_document)
    
    try:
        try:
            pages = await asyncio.to_thread(parse_pdf_pages, file_bytes)
        except Exception:
            raise HTTPException(status_code=422, detail="The PDF could not be read.")

        chunks, page_numbers = await asyncio.to_thread(chunk_pages, pages)

        if not chunks:
            raise HTTPException(
                status_code=422,
                detail="No text could be extracted from this PDF. Scanned documents are not supported.",
            )

        embeddings = await asyncio.to_thread(
            generate_embeddings, [with_document_title(c, file.filename) for c in chunks]
        )

        await upsert_document_chunks(
            collection_name=collection_name,
            document_id=db_document.id,
            chunks=chunks,
            embeddings=embeddings,
            filename=db_document.filename,
            page_numbers=page_numbers
        )

        db_document.page_count = len(pages)
        db_document.chunk_count = len(chunks)
        db_document.is_processed = True
        await db.commit()
        await db.refresh(db_document)

    except Exception as e:
        # Don't keep a document row without vectors
        await db.delete(db_document)
        await db.commit()
        if isinstance(e, HTTPException):
            raise
        logger.exception("Failed to process document %s", file.filename)
        raise HTTPException(status_code=500, detail="Failed to process document.")

    await redis_client.invalidate_user_cache(current_user.id.hex)
    return db_document


@router.get("/", response_model=DocumentListResponse)
async def list_documents(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """List all documents uploaded by the current user."""
    result = await db.execute(
        select(Document)
        .where(Document.user_id == current_user.id)
        .order_by(Document.uploaded_at.desc())
    )
    docs = result.scalars().all()
    
    return {
        "documents": docs,
        "total": len(docs)
    }

@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Delete a document and its vectors."""
    result = await db.execute(
        select(Document)
        .where(Document.id == document_id)
        .where(Document.user_id == current_user.id)
    )
    doc = result.scalar_one_or_none()
    
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
        
    if doc.qdrant_collection:
        await delete_document_chunks(doc.qdrant_collection, doc.id)
        
    await db.delete(doc)
    await db.commit()
    await redis_client.invalidate_user_cache(current_user.id.hex)
    return None
