from typing import List, Tuple
from sentence_transformers import CrossEncoder

from app.core.config import settings

# Load the reranker model into memory
try:
    reranker_model = CrossEncoder(settings.RERANKER_MODEL)
except Exception as e:
    print(f"Warning: Could not load reranker model on startup: {e}")
    reranker_model = None

def rerank_documents(query: str, documents: List[dict], top_k: int = 5) -> List[dict]:
    """
    Re-scores the retrieved documents by passing the (query, document) pair
    through a highly accurate cross-encoder model.
    """
    if not reranker_model:
        raise RuntimeError("Reranker model is not loaded.")
        
    if not documents:
        return []

    # Create pairs of (Query, Document Text) for the model to score
    pairs = [[query, doc["payload"]["text"]] for doc in documents]
    
    # Get precision scores
    scores = reranker_model.predict(pairs)
    
    # Attach scores to documents and sort by highest score
    for i, doc in enumerate(documents):
        doc["relevance_score"] = float(scores[i])
        
    documents.sort(key=lambda x: x["relevance_score"], reverse=True)
    
    # Return only the top_k most relevant chunks
    return documents[:top_k]
