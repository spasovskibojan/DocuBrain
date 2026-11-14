<p align="center">
  <img src="frontend/public/favicon.svg" alt="DocuBrain logo" width="72" height="72" />
</p>

<h1 align="center">DocuBrain</h1>

<p align="center">
  Chat with your PDFs, extract invoice data, compare documents and summarize them.<br/>
  Every answer is grounded in your documents and cites the exact passages it came from.
</p>

<p align="center">
  <a href="https://github.com/spasovskibojan/DocuBrain/actions/workflows/main.yml"><img src="https://github.com/spasovskibojan/DocuBrain/actions/workflows/main.yml/badge.svg" alt="CI/CD" /></a>
  <img src="https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white" alt="Python 3.11" />
  <img src="https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/LangGraph-RAG-1C3C3C" alt="LangGraph" />
  <img src="https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black" alt="React 19" />
  <img src="https://img.shields.io/badge/Kubernetes-k3d-326CE5?logo=kubernetes&logoColor=white" alt="Kubernetes" />
</p>

---

## Features

**Document chat**
- Ask questions across all your documents or scope the chat to a single one.
- Answers carry inline `[n]` citations; each one links to the source passage with its file name and page number.
- If retrieval finds nothing relevant, the assistant says so instead of answering from general knowledge.
- Follow-up questions work: "what about the second one?" is rewritten into a standalone question using the last turns of the conversation, and requests like "make it shorter" reformat the previous answer without a new search.

**Workflows**
- **Invoice extractor** returns vendor, date, total and tax as JSON validated against a Pydantic schema. Invalid output is sent back to the model with the validation error for one retry.
- **Compare documents** lists what changed between two documents, such as two versions of a contract, referring to each by its file name.
- **Executive brief** produces a three-point summary of a document.

**Platform**
- JWT authentication; every user has an isolated vector collection and can only read or delete their own documents.
- Per-user rate limiting on AI endpoints and per-IP limiting on login and registration.
- Repeated questions are answered from a Redis cache, invalidated when the user's documents change.
- Langfuse tracing of every request (pipeline steps, prompts, latency, token usage), enabled by setting the Langfuse keys.

---

## Architecture

```mermaid
flowchart LR
    U[Browser<br/>React SPA] -->|/api, JWT| B

    subgraph B[FastAPI backend]
        direction TB
        API[Routers<br/>auth · documents · query · workflows]
        G[LangGraph RAG pipeline]
        M[Local models<br/>MiniLM embeddings<br/>MS MARCO cross-encoder]
        API --> G --> M
    end

    B --> PG[(PostgreSQL<br/>users, documents,<br/>chat history)]
    B --> Q[(Qdrant<br/>dense + BM25 vectors<br/>one collection per user)]
    B --> R[(Redis<br/>answer cache,<br/>rate limits)]
    B --> LLM[Groq API<br/>gpt-oss-120b / 20b]
    B -.-> LF[Langfuse]
```

### Ingestion

```mermaid
flowchart LR
    UP([PDF upload]) --> V{extension, size,<br/>%PDF- header}
    V -->|invalid| X([400 / 413])
    V -->|valid| P[pdfplumber<br/>text per page]
    P --> CH[chunks<br/>900 chars, 150 overlap]
    CH --> EMB[MiniLM embedding<br/>+ BM25 sparse vector]
    EMB --> Q[(Qdrant<br/>user collection)]
    Q --> OK([document saved,<br/>cache version bumped])
    P -.->|any step fails| RB[delete document row]
    EMB -.-> RB
```

1. The upload is checked for extension, size and the `%PDF-` header.
2. `pdfplumber` extracts text page by page; each page is split into 900-character chunks with 150 overlap, so every chunk keeps its page number. The size fits the 256-token input limit of the embedding model.
3. Each chunk is stored in Qdrant with two vectors: a 384-dim `all-MiniLM-L6-v2` embedding and a BM25 sparse vector computed by the Qdrant server.
4. If any step fails, the document row is removed so the database never lists a document without vectors.

### Question answering

```mermaid
flowchart LR
    S([question]) --> C[condense with<br/>chat history]
    C -->|reformat request| RF[reformat<br/>previous answer] --> E([answer])
    C -->|cached| E
    C -->|new question| RT

    subgraph LangGraph
        RT[retrieve<br/>dense + BM25, RRF top 50] --> RR[rerank<br/>cross-encoder top 5]
        RR -->|score ≥ threshold| GEN[generate<br/>with citations]
        RR -->|low score, first try| RW[rewrite query] --> RT
        RR -->|no chunks| NA[no answer]
    end

    GEN --> E
    NA --> E
```

Dense search finds passages by meaning ("payment deadline" matches "due within 30 days"). BM25 finds exact terms that embeddings handle poorly, such as invoice numbers and company names. Both run in a single Qdrant query and are merged with Reciprocal Rank Fusion before the cross-encoder picks the final five.

### Workflows

```mermaid
flowchart LR
    D([document id]) --> O{owned by user?}
    O -->|no| NF([404])
    O -->|yes| S[read chunks from Qdrant<br/>in reading order]
    S --> W{workflow}
    W -->|invoice| INV[LLM in JSON mode] --> PV{Pydantic valid?}
    PV -->|yes| J([invoice JSON])
    PV -->|no, first try| FB[send validation error back] --> INV
    PV -->|no, second try| E([502])
    W -->|brief| BR[LLM summary] --> B([3-point brief])
    W -->|compare| CMP[LLM diff of two documents] --> DF([list of changes])
```

Workflows skip retrieval: they read the document's chunks directly by index. Invoices use the first and last chunks (vendor at the top, totals at the bottom); briefs and comparisons sample chunks evenly across the document.

### Engineering notes

- **Document title in search text.** Chunks are embedded and reranked with the file name prepended, so a clause like "99.5% availability" still matches a question about "the 2025 agreement". The stored text stays clean.
- **Self-correcting retrieval.** When the best reranked chunk scores below a threshold, the graph rewrites the query once and searches again before generating.
- **Prompt context grouped by document.** Retrieved passages are grouped per document under its file name and put back in reading order, so the model does not mix facts between two similar contracts.
- **Cache invalidation by version.** Cache keys include a per-user version number. Uploading or deleting a document increments it, which makes all old answers unreachable without scanning keys.
- **Redis fails open.** If Redis is unavailable, cache and rate limiting are skipped and requests still succeed; the readiness probe checks only Postgres and Qdrant.
- **Safe migrations with replicas.** Alembic runs on startup under a Postgres advisory lock, so two backend replicas starting together do not migrate at the same time.
- **Models baked into the image.** The embedding and reranker models are downloaded at build time and the container runs with `HF_HUB_OFFLINE=1`, so pods start without network access to Hugging Face.

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | FastAPI, async SQLAlchemy 2, asyncpg, Alembic, Pydantic v2 |
| AI pipeline | LangGraph, LangChain, Groq (`openai/gpt-oss-120b` for answers and workflows, `openai/gpt-oss-20b` for query rewriting) |
| Retrieval | Qdrant hybrid search (dense + BM25, RRF), Sentence Transformers `all-MiniLM-L6-v2`, cross-encoder `ms-marco-MiniLM-L-6-v2` |
| Data | PostgreSQL 16 (JSONB for cited sources in chat history), Redis 7 |
| Observability | Langfuse |
| Auth | JWT (`python-jose`), bcrypt |
| Frontend | React 19, Vite, React Router, React Bootstrap, `react-markdown` |
| Infrastructure | Docker, Docker Compose, Kubernetes (k3d), Traefik Ingress, nginx, GitHub Actions |

---

## Getting started

**Requirements:** Docker with Docker Compose and a free [Groq API key](https://console.groq.com).

```bash
git clone https://github.com/spasovskibojan/DocuBrain.git
cd DocuBrain
```

Create a `.env` file in the project root:

```env
GROQ_API_KEY=your_key_here
SECRET_KEY=any_long_random_string

# Optional: tracing in Langfuse Cloud
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
```

```bash
docker compose up --build -d
```

| Service | URL |
|---|---|
| App | http://localhost:5173 |
| API docs (Swagger) | http://localhost:8000/docs |
| Qdrant dashboard | http://localhost:6333/dashboard |

The first build takes a few minutes because it downloads the CPU build of PyTorch and both models into the image.

To run the whole stack on a local Kubernetes cluster instead, see [docs/deployment.md](docs/deployment.md), which also covers configuration and CI/CD.

---

## Testing

```bash
docker compose exec backend pytest tests/ -v
```

35 tests run against a real PostgreSQL database, with Qdrant and the LLM replaced by fakes, so the suite needs no API keys. They cover auth and rate limiting, upload validation, isolation between users, RAG routing and hybrid search, and the retry logic of the invoice extractor. GitHub Actions runs them on every push and pull request, then builds and pushes the Docker images on `main`.

---

## Evaluation

The `eval/` folder measures answer quality on a golden set of 33 questions over 7 synthetic business documents (4 invoices, 2 versions of the same service agreement, 1 annual report). The questions cover exact IDs, paraphrases, reasoning, comparisons across documents and 3 questions with no answer in the documents. All questions search across every document, which is harder than choosing one document in the UI.

### Retrieval

`retrieval_eval.py` runs inside the backend container and needs no LLM. A chunk counts as relevant if it comes from the expected document and contains the expected fact. Hit@k is the share of questions with a relevant chunk in the top k; MRR averages 1/rank of the first relevant chunk.

| Strategy | Hit@1 before | Hit@1 after title fix | Hit@3 after | MRR after |
|---|---|---|---|---|
| Dense | 0.50 | 0.80 | 0.93 | 0.88 |
| BM25 | 0.73 | 0.87 | 0.97 | 0.92 |
| **Hybrid (used)** | 0.67 | **0.97** | **1.00** | **0.98** |
| Hybrid + reranker | 0.70 | 0.83 | 1.00 | 0.91 |

The first run showed that questions like "What uptime did Summit guarantee in the 2025 agreement?" failed because the chunk with the answer never mentions 2025. Adding the document title to the search text fixed that.

### End-to-end answers

`run_eval.py` uploads the documents as a new user and asks every question through the real API. Deterministic checks look for the expected fact in the answer, the expected document in the sources, citation markers and refusals. RAGAS scores faithfulness and answer accuracy with `qwen/qwen3.8-27b` as the judge, a different model family from the one that writes the answers.

| Metric | Result |
|---|---|
| Expected fact in the answer | 30 / 30 |
| Expected document retrieved | 30 / 30 |
| Answer has citations | 29 / 30 |
| Unanswerable questions refused | 3 / 3 |
| Answerable questions refused | 0 |
| Faithfulness (RAGAS) | 0.86 (29 answers judged) |
| Answer accuracy (RAGAS) | 0.93 |
| Latency p50 / p95 | 8.6 s / 12.1 s |

What the eval caught:

- **Mixed-up contracts.** Asked about the 2025 notice period, the model answered with the 2026 value, although the right chunk was retrieved. The prompt did not say which file each passage came from, so two near-identical contracts looked the same. Passages are now grouped under their file name.
- **Clause numbers as citations.** On contracts, the model sometimes cited section numbers like `[7.1]` instead of passage numbers. A prompt rule fixed most cases; one cross-document question still sometimes lists its sources in words instead of `[n]`.
- **The judge had the same blind spot.** All 4 answers with faithfulness 0 are correct contract answers. The judge received the chunks without file names, so it could not confirm that a clause belongs to "the 2025 agreement". The judge now gets the same document names as the answer model: 15 answers re-judged this way all scored 1.0, and one of the four zeros went from 0 to 1.0. A full re-run with names did not fit in the Groq daily limit, so the table shows the first run.

Answer accuracy is below 1.0 for 7 answers. Six are correct but leave out an extra detail of the reference, such as the 10.1% tax rate next to the tax amount; the seventh adds a difference ($250) that the reference does not state. One cross-document question could not be judged for faithfulness because its prompt exceeds the free-tier request size.

Limitations of this eval:

- 30 answerable questions over 31 chunks is a small set, so one question moves a score by about 3 points.
- The title fix was designed after seeing the failing questions and measured on the same questions, so the gain is likely smaller on new data.
- The reranker lowers Hit@1 on this small corpus. Answers are not affected because the model receives the top 5 chunks and the right one is always among them, but the reranker should be re-evaluated on a larger document set.
- The sample documents are not included in the repository. To run the eval on your own documents, update `eval/dataset.json` and pass `--docs`.

```bash
# Retrieval, inside the backend container
docker compose cp eval backend:/tmp/eval
docker compose cp samples backend:/tmp/samples
docker compose exec backend python /tmp/eval/retrieval_eval.py /tmp/samples

# End-to-end, against the running API (separate environment, see eval/requirements.txt)
python -m venv eval/.venv && eval/.venv/Scripts/pip install -r eval/requirements.txt
GROQ_API_KEY=... eval/.venv/Scripts/python eval/run_eval.py --docs samples --label hybrid
```

---

## Project structure

```
├── backend/
│   ├── app/
│   │   ├── api/          # auth, documents, query, workflows routers
│   │   ├── core/         # config, database, security, Redis client, tracing
│   │   ├── models/       # SQLAlchemy models
│   │   ├── schemas/      # Pydantic schemas
│   │   └── services/     # RAG pipeline, embeddings, reranker, Qdrant, PDF parsing
│   ├── alembic/          # database migrations
│   └── tests/
├── frontend/src/
│   ├── pages/
│   ├── components/
│   └── services/         # Axios client with JWT interceptor
├── eval/                 # golden set, retrieval and end-to-end evaluation
├── k8s/                  # Kubernetes manifests and start/stop scripts
└── docs/
```

---

## Limitations

- Only text-based PDFs are supported; scanned documents are rejected because there is no OCR step.
- To stay within the Groq free-tier limit of 6,000 tokens per minute, workflows on long documents read a sample of chunks instead of the full text. Typical invoices are short enough to be read in full; summaries and comparisons of longer documents can miss content.
- CORS is open to all origins; it should be restricted to the frontend domain before a public deployment.
