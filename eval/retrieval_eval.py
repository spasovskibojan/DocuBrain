"""Compares retrieval strategies on the golden set, without any LLM calls.

Runs inside the backend container, which has the embedding models and Qdrant:
    docker compose cp eval backend:/tmp/eval
    docker compose cp samples backend:/tmp/samples
    docker compose exec backend python /tmp/eval/retrieval_eval.py /tmp/samples
"""
import asyncio
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, "/app")

from qdrant_client.http import models  # noqa: E402

from app.services.embeddings import generate_embeddings  # noqa: E402
from app.services.pdf_parser import chunk_pages, parse_pdf_pages, with_document_title  # noqa: E402
from app.services.qdrant_service import DENSE_VECTOR, SPARSE_VECTOR, bm25, qdrant_client, upsert_document_chunks  # noqa: E402
from app.services.reranker import rerank_documents  # noqa: E402

COLLECTION = f"eval_retrieval_{uuid.uuid4().hex[:8]}"
CANDIDATES = 50
KS = (1, 3, 5)


async def index_documents(docs_dir: Path) -> int:
    total = 0
    for pdf in sorted(docs_dir.glob("*.pdf")):
        chunks, pages = chunk_pages(parse_pdf_pages(pdf.read_bytes()))
        await upsert_document_chunks(COLLECTION, uuid.uuid4(), chunks, generate_embeddings([with_document_title(c, pdf.name) for c in chunks]), pdf.name, pages)
        total += len(chunks)
    return total


async def search(question: str, vector: list[float], strategy: str) -> list[dict]:
    dense = models.Prefetch(query=vector, using=DENSE_VECTOR, limit=CANDIDATES)
    sparse = models.Prefetch(query=bm25(question), using=SPARSE_VECTOR, limit=CANDIDATES)
    if strategy == "dense":
        result = await qdrant_client.query_points(COLLECTION, query=vector, using=DENSE_VECTOR, limit=CANDIDATES)
    elif strategy == "bm25":
        result = await qdrant_client.query_points(COLLECTION, query=bm25(question), using=SPARSE_VECTOR, limit=CANDIDATES)
    else:
        result = await qdrant_client.query_points(
            COLLECTION, prefetch=[dense, sparse], query=models.FusionQuery(fusion=models.Fusion.RRF), limit=CANDIDATES
        )
    return [{"payload": p.payload} for p in result.points]


def is_relevant(chunk: dict, item: dict) -> bool:
    payload = chunk["payload"]
    return payload["filename"] in item["sources"] and any(f.lower() in payload["text"].lower() for f in item["facts"])


def first_hit(ranking: list[dict], item: dict) -> int | None:
    return next((rank for rank, chunk in enumerate(ranking, start=1) if is_relevant(chunk, item)), None)


async def main(docs_dir: Path) -> None:
    dataset = [i for i in json.loads((Path(__file__).parent / "dataset.json").read_text()) if i["sources"]]
    chunk_total = await index_documents(docs_dir)
    strategies = ["dense", "bm25", "hybrid", "dense+rerank", "hybrid+rerank"]
    ranks: dict[str, list[int | None]] = {s: [] for s in strategies}
    misses: dict[str, list[str]] = {s: [] for s in strategies}

    try:
        for item in dataset:
            vector = generate_embeddings([item["question"]])[0]
            for strategy in strategies:
                base = strategy.split("+")[0]
                ranking = await search(item["question"], vector, base)
                if strategy.endswith("+rerank"):
                    ranking = rerank_documents(item["question"], ranking, top_k=CANDIDATES)
                rank = first_hit(ranking, item)
                ranks[strategy].append(rank)
                if rank is None or rank > 5:
                    misses[strategy].append(f"[{item['type']}] {item['question']}")
    finally:
        await qdrant_client.delete_collection(COLLECTION)

    summary = {}
    for strategy, values in ranks.items():
        n = len(values)
        row = {f"hit@{k}": sum(1 for r in values if r and r <= k) / n for k in KS}
        row["mrr"] = sum(1 / r for r in values if r) / n
        summary[strategy] = {key: round(value, 3) for key, value in row.items()}

    print(f"\n{len(dataset)} questions, {chunk_total} chunks\n")
    print("| Strategy | Hit@1 | Hit@3 | Hit@5 | MRR |")
    print("|---|---|---|---|---|")
    for strategy, row in summary.items():
        print(f"| {strategy} | {row['hit@1']:.2f} | {row['hit@3']:.2f} | {row['hit@5']:.2f} | {row['mrr']:.2f} |")
    for strategy in strategies:
        if misses[strategy]:
            print(f"\nNot in top 5 with {strategy}:")
            print("\n".join(f"  {m}" for m in misses[strategy]))

    print("\nJSON:", json.dumps({"questions": len(dataset), "chunks": chunk_total, "results": summary}))


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/samples")))
