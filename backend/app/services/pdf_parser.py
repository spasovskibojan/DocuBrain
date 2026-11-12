import io
from pathlib import PurePath
from typing import List

import pdfplumber
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import settings


def parse_pdf_pages(file_bytes: bytes) -> List[str]:
    """Extracts the text of every page of a PDF file in memory."""
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        return [page.extract_text() or "" for page in pdf.pages]


def chunk_text(text: str) -> List[str]:
    """Splits a long document into smaller semantic chunks for vector storage."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.CHUNK_SIZE,
        chunk_overlap=settings.CHUNK_OVERLAP,
        separators=["\n\n", "\n", " ", ""]
    )
    
    return splitter.split_text(text)


def chunk_pages(pages: List[str]) -> tuple[List[str], List[int]]:
    """Chunks each page on its own so every chunk keeps its 1-based page number."""
    chunks: List[str] = []
    page_numbers: List[int] = []

    for page_number, page_text in enumerate(pages, start=1):
        page_chunks = chunk_text(page_text)
        chunks.extend(page_chunks)
        page_numbers.extend([page_number] * len(page_chunks))

    return chunks, page_numbers


def with_document_title(chunk: str, filename: str | None) -> str:
    """Prefixes a chunk with its document name for search, so a clause like "99.5% availability"
    still matches a question about "the 2025 agreement"."""
    if not filename:
        return chunk
    title = PurePath(filename).stem.replace("_", " ").replace("-", " ")
    return f"{title}\n{chunk}"
