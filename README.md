# DocuBrain AI 🧠

**An Enterprise-Grade AI Document Intelligence Platform for Accounting Firms**

Built as a university capstone project demonstrating modern AI engineering: RAG pipelines, vector databases, agentic workflows, and production-grade DevOps.

---

## 🏗️ Architecture

| Service | Technology | Purpose |
|---|---|---|
| **Frontend** | React + Vite | SPA User Interface |
| **Backend** | FastAPI + LangGraph | AI Orchestration & API |
| **PostgreSQL** | Postgres 16 | User data & chat history |
| **Qdrant** | Qdrant Vector DB | Semantic document search |
| **Redis** | Redis 7 | API caching & rate limiting |

## ✨ Features

- 🔐 **Secure Multi-Tenant Auth** — JWT-based authentication
- 📄 **RAG Document Chat** — Hybrid search with cross-encoder reranking
- 🧾 **Invoice Extractor** — Automatic structured data extraction (Vendor, Date, Total, Tax)
- ⚖️ **Contract Diff** — AI-powered legal clause comparison
- ⚡ **Executive Brief** — Instant 3-bullet financial summaries
- 🚫 **Zero Hallucination** — Strict RAG with verifiable source citations

## 🚀 Quick Start (Local)

### Prerequisites
- Docker & Docker Compose
- A [Groq API Key](https://console.groq.com) (free)

### 1. Clone and configure

```bash
git clone https://github.com/spasovskibojan/DocuBrain.git
cd DocuBrain
```

Create a `.env` file in the root:
```env
GROQ_API_KEY=your_groq_api_key_here
```

### 2. Start all services

```bash
docker compose up --build -d
```

### 3. Access the app

| Service | URL |
|---|---|
| Frontend | http://localhost:5173 |
| Backend API Docs | http://localhost:8000/docs |

---

## 🔄 CI/CD Pipeline (GitHub Actions)

On every push to `main`:
1. ✅ Runs backend `pytest` tests
2. 🐳 Builds Docker images for Backend and Frontend
3. 📦 Pushes images to DockerHub with `latest` and `git-sha` tags

**Required GitHub Secrets:**
| Secret | Description |
|---|---|
| `DOCKERHUB_USERNAME` | Your DockerHub username |
| `DOCKERHUB_TOKEN` | Your DockerHub access token |
| `GROQ_API_KEY` | Your Groq API key for tests |

---

## ☸️ Kubernetes Deployment

All manifests are in the `k8s/` directory.

```bash
# Deploy to your cluster (Minikube, Kind, or cloud)
bash k8s/deploy.sh
```

**Manifest Overview:**

| File | Resource | Description |
|---|---|---|
| `00-namespace.yaml` | Namespace | `docubrain` isolation |
| `01-secrets.yaml` | Secret | Encrypted API keys & passwords |
| `02-configmap.yaml` | ConfigMap | Non-sensitive configuration |
| `03-statefulsets.yaml` | StatefulSet × 3 | Postgres, Qdrant, Redis with PVCs |
| `04-deployments.yaml` | Deployment × 2 | Backend (2 replicas), Frontend (2 replicas) |
| `05-services.yaml` | Service × 2 | ClusterIP for Backend & Frontend |
| `06-ingress.yaml` | Ingress | Routes `docubrain.local` → Frontend, `api.docubrain.local` → Backend |

### Local Minikube Testing
```bash
minikube start
minikube addons enable ingress
bash k8s/deploy.sh
# Add to /etc/hosts: <minikube ip> docubrain.local api.docubrain.local
```

---

## 🛠️ Tech Stack

- **AI:** LangGraph, LangChain, Groq (llama-3.1-8b-instant), Sentence Transformers
- **Backend:** FastAPI, SQLAlchemy (async), Alembic, Pydantic v2
- **Frontend:** React 18, Vite, Bootstrap 5, Lucide Icons
- **Infrastructure:** Docker, Docker Compose, GitHub Actions, Kubernetes

