import uuid
from typing import List

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models

from app.core.config import settings

# cloud_inference lets the Qdrant server compute the BM25 vectors from text
qdrant_client = AsyncQdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT, cloud_inference=True)

# Output size of all-MiniLM-L6-v2
VECTOR_SIZE = 384
DENSE_VECTOR = "dense"
SPARSE_VECTOR = "bm25"
BM25_MODEL = "qdrant/bm25"


def bm25(text: str) -> models.Document:
    return models.Document(text=text, model=BM25_MODEL)


async def ensure_collection_exists(collection_name: str) -> None:
    """Creates a Qdrant collection for a specific user if it doesn't already exist."""
    exists = await qdrant_client.collection_exists(collection_name)
    if not exists:
        await qdrant_client.create_collection(
            collection_name=collection_name,
            vectors_config={
                DENSE_VECTOR: models.VectorParams(size=VECTOR_SIZE, distance=models.Distance.COSINE)
            },
            sparse_vectors_config={
                SPARSE_VECTOR: models.SparseVectorParams(modifier=models.Modifier.IDF)
            },
        )

async def upsert_document_chunks(
    collection_name: str, 
    document_id: uuid.UUID, 
    chunks: List[str], 
    embeddings: List[List[float]],
    filename: str | None = None,
    page_numbers: List[int] | None = None
) -> None:
    """Inserts chunk vectors and their payload (metadata) into Qdrant."""
    
    await ensure_collection_exists(collection_name)
    
    points = []
    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        point = models.PointStruct(
            id=str(uuid.uuid4()),
            vector={DENSE_VECTOR: embedding, SPARSE_VECTOR: bm25(chunk)},
            payload={
                "document_id": str(document_id),
                "chunk_index": i,
                "filename": filename,
                "page_number": page_numbers[i] if page_numbers else 1,
                "text": chunk
            }
        )
        points.append(point)
        
    await qdrant_client.upsert(
        collection_name=collection_name,
        points=points
    )

async def delete_document_chunks(collection_name: str, document_id: uuid.UUID) -> None:
    """Deletes all chunks associated with a specific document from Qdrant."""
    exists = await qdrant_client.collection_exists(collection_name)
    if not exists:
        return
        
    await qdrant_client.delete(
        collection_name=collection_name,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id",
                        match=models.MatchValue(value=str(document_id))
                    )
                ]
            )
        )
    )
