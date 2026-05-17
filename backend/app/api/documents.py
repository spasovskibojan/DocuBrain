import uuid
from typing import Annotated, List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.document import Document
from app.models.user import User
from app.schemas.document import DocumentResponse, DocumentListResponse
from app.services.embeddings import generate_embeddings
from app.services.pdf_parser import chunk_text, parse_pdf_to_text
from app.services.qdrant_service import upsert_document_chunks, delete_document_chunks

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

    # 1. Read file into memory
    file_bytes = await file.read()
    file_size = len(file_bytes)
    
    # Define collection name unique to this user
    collection_name = f"user_{current_user.id.hex}_docs"
    
    # 2. Create the Database Record (initially unprocessed)
    db_document = Document(
        user_id=current_user.id,
        filename=file.filename,
        original_filename=file.filename,
        file_size_bytes=file_size,
        qdrant_collection=collection_name,
        is_processed=False
    )
    db.add(db_document)
    await db.commit()
    await db.refresh(db_document)
    
    try:
        # 3. Parse PDF to raw text
        raw_text = parse_pdf_to_text(file_bytes)
        
        # 4. Split text into 512-character chunks
        chunks = chunk_text(raw_text)
        
        if not chunks:
            raise ValueError("No text could be extracted from this PDF.")
            
        # 5. Generate Vectors (Embeddings)
        embeddings = generate_embeddings(chunks)
        
        # 6. Save vectors to Qdrant Vector DB
        await upsert_document_chunks(
            collection_name=collection_name,
            document_id=db_document.id,
            chunks=chunks,
            embeddings=embeddings
        )
        
        # 7. Update PostgreSQL record to processed
        db_document.chunk_count = len(chunks)
        db_document.is_processed = True
        await db.commit()
        await db.refresh(db_document)
        
    except Exception as e:
        # If anything fails, delete the record so we don't have broken state
        await db.delete(db_document)
        await db.commit()
        raise HTTPException(status_code=500, detail=f"Failed to process document: {str(e)}")

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
        
    # Delete from Qdrant
    if doc.qdrant_collection:
        await delete_document_chunks(doc.qdrant_collection, doc.id)
        
    # Delete from Database
    await db.delete(doc)
    await db.commit()
    return None
