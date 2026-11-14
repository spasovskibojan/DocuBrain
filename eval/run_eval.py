"""End-to-end evaluation of the running DocuBrain API with RAGAS.

Uploads the sample documents as a fresh user, asks every golden-set question through
/api/query/ask, then scores the answers with deterministic checks and RAGAS metrics.
A different model family (Qwen) is the judge, so gpt-oss never grades its own answers.

    eval/.venv/Scripts/python eval/run_eval.py --docs samples --label hybrid
"""
import argparse
import asyncio
import json
import math
import os
import re
import statistics
import time
import uuid
from datetime import date
from pathlib import Path

import httpx
from openai import AsyncOpenAI
from ragas.llms import llm_factory
from ragas.metrics.collections import AnswerAccuracy, Faithfulness

EVAL_DIR = Path(__file__).parent
REFUSALS = (
    "don't know", "do not know", "couldn't find", "could not find", "not in your documents",
    "no information", "does not contain", "doesn't contain", "not mentioned", "not specified", "do not contain",
    "not provided", "does not include", "doesn't include", "no mention",
)
PASSWORD = "Eval-Passw0rd-123"
JUDGE_ATTEMPTS = 6


def normalize(text: str) -> str:
    # gpt-oss writes non-breaking hyphens and spaces inside IDs and amounts
    text = re.sub(r"[‐‑‒–]", "-", text)
    text = re.sub(r"[  ]", " ", text)
    return re.sub(r"\s+%", "%", text).lower()


def is_scored(value) -> bool:
    return value is not None and not math.isnan(value)


def retry_delay(error: str) -> float:
    # Groq says how long to wait in the 429 message ("Please try again in 22.3s")
    match = re.search(r"try again in (\d+(?:\.\d+)?)s", error)
    return float(match.group(1)) + 1 if match else 20


def is_refusal(answer: str) -> bool:
    return any(phrase in normalize(answer) for phrase in REFUSALS)


async def ask_all(api: str, docs: Path, dataset: list[dict]) -> list[dict]:
    async with httpx.AsyncClient(base_url=api, timeout=120) as client:
        email = f"eval_{uuid.uuid4().hex[:8]}@example.com"
        await client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
        token = (await client.post("/api/auth/login", json={"email": email, "password": PASSWORD})).json()["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"

        doc_ids = []
        for pdf in sorted(docs.glob("*.pdf")):
            response = await client.post("/api/documents/upload", files={"file": (pdf.name, pdf.read_bytes(), "application/pdf")})
            response.raise_for_status()
            doc_ids.append(response.json()["id"])

        rows = []
        try:
            for i, item in enumerate(dataset, start=1):
                # Every question starts a new conversation, so earlier answers can't leak in
                await client.delete("/api/query/history")
                while True:
                    started = time.perf_counter()
                    response = await client.post("/api/query/ask", json={"question": item["question"]})
                    if response.status_code != 429:
                        break
                    await asyncio.sleep(int(response.headers.get("Retry-After", 10)) + 1)
                response.raise_for_status()
                data = response.json()
                rows.append({
                    **item,
                    "answer": data["answer"],
                    "contexts": [s["chunk_text"] for s in data["sources"]],
                    "retrieved_sources": [s["document_name"] for s in data["sources"]],
                    "latency_s": round(time.perf_counter() - started, 2),
                })
                print(f"[{i}/{len(dataset)}] {rows[-1]['latency_s']}s  {item['question']}")
        finally:
            await client.delete("/api/query/history")
            for doc_id in doc_ids:
                await client.delete(f"/api/documents/{doc_id}")
        return rows


async def judge(rows: list[dict], model: str) -> None:
    client = AsyncOpenAI(base_url="https://api.groq.com/openai/v1", api_key=os.environ["GROQ_API_KEY"])
    # Thinking tokens count toward the Groq daily limit and add little to these yes/no judgments
    llm = llm_factory(model, client=client, temperature=0, extra_body={"reasoning_effort": "none"})
    # Retrieval is scored by retrieval_eval.py without an LLM, so the judge's daily
    # token budget goes only to what needs one: grounding and correctness
    metrics = {
        "faithfulness": (Faithfulness(llm=llm), ("user_input", "response", "retrieved_contexts")),
        "answer_accuracy": (AnswerAccuracy(llm=llm), ("user_input", "response", "reference")),
    }
    # The free tier allows ~7k input tokens per minute, so requests go one at a time
    limit = asyncio.Semaphore(1)

    async def score(row: dict, name: str) -> None:
        if is_scored(row.get(name)):
            return
        metric, fields = metrics[name]
        # The judge sees the document names the answer model saw; without them two near-identical
        # contracts can't be told apart and correct "2025 agreement" claims look unsupported
        contexts = [f"Document: {source}\n{text}" for source, text in zip(row["retrieved_sources"], row["contexts"])]
        values = {"user_input": row["question"], "response": row["answer"],
                  "retrieved_contexts": contexts, "reference": row["reference"]}
        async with limit:
            for attempt in range(JUDGE_ATTEMPTS):
                try:
                    result = await metric.ascore(**{f: values[f] for f in fields})
                    value = float(result.value)
                    row[name] = None if math.isnan(value) else round(value, 3)
                    if row[name] is not None:
                        return
                    error = "judge returned NaN"
                except Exception as exc:  # rate limits and malformed judge output
                    error = str(exc)
                    # Neither clears up by waiting a few seconds
                    if "tokens per day" in error or "Request too large" in error:
                        break
                await asyncio.sleep(retry_delay(error))
            print(f"  {name} not scored for '{row['question']}': {error[:120]}")

    answerable = [r for r in rows if r["reference"]]
    # Metric by metric, so a daily-limit stop still leaves complete columns to report
    await asyncio.gather(*(score(r, name) for name in metrics for r in answerable))


def summarize(rows: list[dict]) -> dict:
    answerable = [r for r in rows if r["reference"]]
    unanswerable = [r for r in rows if not r["reference"]]
    for r in answerable:
        r["facts_found"] = all(normalize(f) in normalize(r["answer"]) for f in r["facts"])
        r["source_found"] = any(s in r["retrieved_sources"] for s in r["sources"])
        r["cited"] = bool(re.search(r"\[\d+\]", r["answer"]))
    for r in unanswerable:
        r["refused"] = is_refusal(r["answer"])

    def mean(key: str) -> float | None:
        values = [r[key] for r in answerable if is_scored(r.get(key))]
        return round(statistics.mean(values), 3) if values else None

    latencies = sorted(r["latency_s"] for r in rows)
    return {
        "questions": len(rows),
        "faithfulness": mean("faithfulness"),
        "answer_accuracy": mean("answer_accuracy"),
        "facts_found": mean("facts_found"),
        "source_found": mean("source_found"),
        "cited": mean("cited"),
        "false_refusals": sum(is_refusal(r["answer"]) for r in answerable),
        "correct_refusals": f"{sum(r['refused'] for r in unanswerable)}/{len(unanswerable)}",
        "latency_p50_s": latencies[len(latencies) // 2],
        "latency_p95_s": latencies[int(len(latencies) * 0.95) - 1],
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--docs", type=Path, default=EVAL_DIR.parent / "samples")
    parser.add_argument("--label", default="hybrid")
    parser.add_argument("--judge", default="qwen/qwen3.8-27b")
    parser.add_argument("--resume", type=Path, help="results file whose missing scores should be judged")
    args = parser.parse_args()

    if args.resume:
        out = args.resume
        rows = json.loads(out.read_text(encoding="utf-8"))["rows"]
    else:
        dataset = json.loads((EVAL_DIR / "dataset.json").read_text(encoding="utf-8"))
        rows = await ask_all(args.api, args.docs, dataset)
        out = EVAL_DIR / "results" / f"e2e_{args.label}_{date.today()}.json"
        out.parent.mkdir(exist_ok=True)

    def save(summary: dict | None) -> None:
        out.write_text(json.dumps({"label": args.label, "judge": args.judge, "summary": summary, "rows": rows}, indent=2, ensure_ascii=False), encoding="utf-8")

    # Answers are saved first, so a judge that hits the Groq daily limit can be resumed later
    save(None)
    print(f"\nJudging with {args.judge}...")
    await judge(rows, args.judge)
    summary = summarize(rows)
    save(summary)

    print("\n| Metric | Value |\n|---|---|")
    for key, value in summary.items():
        print(f"| {key} | {value} |")
    print("\nFailed checks:")
    for r in rows:
        problems = [k for k in ("facts_found", "source_found") if r.get(k) is False]
        problems += [k for k in ("faithfulness", "answer_accuracy") if (r.get(k) or 1) < 0.5]
        if r.get("refused") is False:
            problems.append("did not refuse")
        if problems:
            print(f"  [{r['type']}] {r['question']}: {', '.join(problems)}\n      -> {r['answer'][:160]}")
    print(f"\nSaved {out}")


if __name__ == "__main__":
    asyncio.run(main())
