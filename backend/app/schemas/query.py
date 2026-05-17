import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class SourceChunk(BaseModel):
    """One retrieved document chunk that supported the answer."""
    document_id: str
    document_name: str
    page_number: int
    chunk_text: str
    relevance_score: float


class QueryRequest(BaseModel):
    question: str
    document_id: Optional[uuid.UUID] = None  # None = search all user's documents


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceChunk]
    from_cache: bool
    query_id: uuid.UUID


class QueryHistoryResponse(BaseModel):
    id: uuid.UUID
    question: str
    answer: str
    source_chunks: Optional[list] = None
    from_cache: bool
    created_at: datetime

    model_config = {"from_attributes": True}
