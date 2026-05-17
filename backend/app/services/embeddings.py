from typing import List
from sentence_transformers import SentenceTransformer

from app.core.config import settings

# Load the embedding model as a singleton so it stays in memory
# all-MiniLM-L6-v2 outputs a 384-dimensional vector. It's fast and highly effective for RAG.
try:
    embedding_model = SentenceTransformer(settings.EMBEDDING_MODEL)
except Exception as e:
    print(f"Warning: Could not load embedding model on startup: {e}")
    embedding_model = None

def generate_embeddings(texts: List[str]) -> List[List[float]]:
    """Converts a list of text strings into vector embeddings."""
    if not embedding_model:
        raise RuntimeError("Embedding model is not loaded.")
    
    # encode() returns a numpy array, we convert to standard python list for Qdrant
    embeddings = embedding_model.encode(texts, show_progress_bar=False)
    return embeddings.tolist()
