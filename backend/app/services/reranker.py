import threading
from typing import List, Tuple
from sentence_transformers import CrossEncoder

from app.core.config import settings

try:
    reranker_model = CrossEncoder(settings.RERANKER_MODEL)
except Exception as e:
    print(f"Warning: Could not load reranker model on startup: {e}")
    reranker_model = None

# Called from worker threads; the tokenizer cannot be shared by concurrent calls
_model_lock = threading.Lock()


def rerank_documents(query: str, documents: List[dict], top_k: int = 5) -> List[dict]:
    """
    Re-scores the retrieved documents by passing the (query, document) pair
    through a highly accurate cross-encoder model.
    """
    if not reranker_model:
        raise RuntimeError("Reranker model is not loaded.")
        
    if not documents:
        return []

    pairs = [[query, doc["payload"]["text"]] for doc in documents]
    
    with _model_lock:
        scores = reranker_model.predict(pairs)
    
    for i, doc in enumerate(documents):
        doc["relevance_score"] = float(scores[i])
        
    documents.sort(key=lambda x: x["relevance_score"], reverse=True)
    
    return documents[:top_k]
