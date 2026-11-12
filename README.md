# DocuBrain

**An AI-powered document intelligence platform built with RAG, vector search, and LLM workflows.**

DocuBrain lets users upload PDFs and interact with them through natural language — asking questions, extracting structured data, comparing contracts, and generating executive summaries. Built as a university capstone project, the goal was to apply production-grade engineering practices to a non-trivial AI system.

---

## What it does

| Feature | Description |
|---|---|
| **Document Chat** | Upload a PDF and ask questions. Answers are generated only from the retrieved chunks, with inline `[n]` citations linked to the source passages; if nothing relevant is found, it says so. |
| **Invoice Extractor** | Extracts structured fields (Vendor, Date, Total, Tax) from an invoice as schema-validated JSON. |
| **Contract Diff** | Side-by-side AI comparison of legal clauses across two documents. |
| **Executive Brief** | Generates a 3-bullet financial summary from any uploaded document. |

---

## Architecture

```
┌─────────────┐     HTTP/JWT      ┌──────────────────────────────────────┐
│  React SPA  │ ◄────────────────► │           FastAPI Backend            │
│  (Vite 5)   │                   │                                      │
└─────────────┘                   │  ┌─────────┐  ┌──────────────────┐  │
                                  │  │ LangGraph│  │ Sentence         │  │
                                  │  │ Workflows│  │ Transformers     │  │
                                  │  └────┬─────┘  │ all-MiniLM-L6-v2│  │
                                  │       │         └────────┬─────────┘  │
                                  └───────┼──────────────────┼────────────┘
                                          │                  │
               ┌──────────────────────────┼──────────────────┼──────────┐
               │                          │                  │          │
          ┌────▼─────┐             ┌──────▼──────┐   ┌──────▼──────┐   │
          │  Groq    │             │   Qdrant    │   │  PostgreSQL │   │
          │  LLM API │             │ Vector DB   │   │  (metadata) │   │
          └──────────┘             └─────────────┘   └─────────────┘   │
                                                                         │
                                                            ┌──────────┐ │
                                                            │  Redis   │ │
                                                            │  cache   │ │
                                                            └──────────┘ │
                                                                         │
               └─────────────────────────────────────────────────────────┘
```

**Request flow for document chat:**
1. User uploads PDF → `pdfplumber` extracts text → chunked with `RecursiveCharacterTextSplitter` (900 chars, 150 overlap, sized to the embedding model's 256-token limit)
2. Each chunk is stored in a per-user Qdrant collection with two vectors: a dense `all-MiniLM-L6-v2` embedding (384-dim) and a BM25 sparse vector computed by the Qdrant server
3. On query: dense and BM25 search run in one Qdrant call and are merged with Reciprocal Rank Fusion (top-50) → cross-encoder reranked to top-5 → sent to Groq LLM, which cites the passages it used as `[n]`
4. Answer + source chunks saved to PostgreSQL query history

Dense search finds passages by meaning ("payment deadline" → "due within 30 days"); BM25 finds exact terms that embeddings handle poorly, such as invoice numbers and company names.

---

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| **Backend** | FastAPI + async SQLAlchemy | Native async I/O — no thread-pool blocking for DB or vector queries |
| **AI orchestration** | LangGraph | Graph-based RAG pipeline with conditional routing and query rewriting |
| **Embeddings** | Sentence Transformers (`all-MiniLM-L6-v2`) | Fast, self-hosted, no per-query API cost |
| **Vector DB** | Qdrant | Per-user collection isolation; hybrid dense + BM25 search with server-side fusion |
| **Tracing** | Langfuse (optional) | One trace per chat request: every LangGraph step, prompt, latency and token usage |
| **Reranking** | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Reranking 50→5 candidates improves retrieval precision significantly over cosine alone |
| **LLM** | Groq (`openai/gpt-oss-120b` for answers, `openai/gpt-oss-20b` for query rewriting) | Low inference latency; free tier sufficient for a demo |
| **Database** | PostgreSQL 16 + asyncpg | JSONB for source-chunk citations in query history |
| **Cache** | Redis 7 | Rate limiting and response caching on repeated queries |
| **Frontend** | React 19 + Vite | Fast HMR in dev; lightweight bundle for a utility-focused app |
| **Auth** | JWT (python-jose) + bcrypt | Stateless, no session store needed |

---

## Running locally

**Prerequisites:** Docker, Docker Compose, a free [Groq API key](https://console.groq.com)

```bash
git clone https://github.com/spasovskibojan/DocuBrain.git
cd DocuBrain
```

Create `.env` in the project root:
```env
GROQ_API_KEY=your_key_here

# Optional: enables tracing in Langfuse Cloud
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
```

```bash
docker compose up --build -d
```

| Service | URL |
|---|---|
| Frontend | http://localhost:5173 |
| Backend API docs | http://localhost:8000/docs |
| Qdrant dashboard | http://localhost:6333/dashboard |

---

## CI/CD

GitHub Actions pipeline on every push to `main`:

1. **Test** — runs `pytest` against a live Postgres service container
2. **Build** — builds backend and frontend Docker images
3. **Push** — publishes to DockerHub with `latest` and `git-sha` tags

Required secrets: `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`, `GROQ_API_KEY`

---

## Kubernetes deployment

All manifests live in `k8s/`. The stack runs on k3d locally but targets any standard Kubernetes cluster.

```powershell
.\k8s\start.ps1   # builds images, creates the cluster, deploys, port-forwards, opens http://localhost:5173
.\k8s\stop.ps1    # stops port-forwards and deletes the cluster
```

The committed `01-secrets.yaml` holds placeholder values only; `start.ps1` patches the real `GROQ_API_KEY` from `.env` into the cluster Secret.

| Manifest | Resources |
|---|---|
| `00-namespace.yaml` | `docubrain` namespace |
| `01-secrets.yaml` | API keys and passwords |
| `02-configmap.yaml` | Non-sensitive config |
| `03-statefulsets.yaml` | Postgres, Qdrant, Redis — each with a PersistentVolumeClaim |
| `04-deployments.yaml` | Backend × 2 replicas, Frontend × 2 replicas |
| `05-services.yaml` | ClusterIP for backend and frontend |
| `06-ingress.yaml` | Routes `docubrain.local` → frontend, `api.docubrain.local` → backend |

---

## Project structure

```
├── backend/
│   ├── app/
│   │   ├── api/          # Route handlers (auth, documents, query, workflows)
│   │   ├── core/         # Config, DB session, security, Redis client
│   │   ├── models/       # SQLAlchemy ORM models
│   │   ├── schemas/      # Pydantic request/response schemas
│   │   └── services/     # RAG pipeline, embeddings, reranker, Qdrant, PDF parser
│   ├── tests/
│   └── main.py
├── frontend/
│   └── src/
│       ├── pages/        # Login, Dashboard, Chat, Upload, Workflows, Extractor, Diff, Brief
│       ├── components/
│       └── services/     # Axios API client with JWT interceptor
├── k8s/                  # Kubernetes manifests
└── docker-compose.yml
```
