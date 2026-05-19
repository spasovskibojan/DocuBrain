import io
from typing import List

import pdfplumber
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import settings


def parse_pdf_to_text(file_bytes: bytes) -> str:
    """Extracts text from a PDF file in memory."""
    text_content = []
    
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_content.append(page_text)
                
    return "\n\n".join(text_content)


def chunk_text(text: str) -> List[str]:
    """Splits a long document into smaller semantic chunks for vector storage."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.CHUNK_SIZE,
        chunk_overlap=settings.CHUNK_OVERLAP,
        separators=["\n\n", "\n", " ", ""]
    )
    
    return splitter.split_text(text)
