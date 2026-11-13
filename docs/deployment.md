# Deployment

## Configuration

All settings live in [`backend/app/core/config.py`](../backend/app/core/config.py) and can be overridden with environment variables.

| Variable | Default | Purpose |
|---|---|---|
| `GROQ_API_KEY` | – | Required for all LLM calls |
| `SECRET_KEY` | – | JWT signing key; the app does not start without it |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | empty | Tracing is enabled only when both are set |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | 900 / 150 | Chunking, in characters |
| `TOP_K_RETRIEVAL` / `TOP_K_RERANK` | 50 / 5 | Candidates from hybrid search / passages sent to the LLM |
| `RELEVANCE_THRESHOLD` | -3.0 | Cross-encoder score below which the query is rewritten |
| `HYBRID_SEARCH` | true | `false` searches dense vectors only |
| `CHAT_HISTORY_TURNS` | 3 | Turns used to resolve follow-up questions |
| `RATE_LIMIT_REQUESTS` | 10 | AI requests per user per minute |
| `CACHE_TTL_SECONDS` | 3600 | Lifetime of cached answers |
| `MAX_UPLOAD_SIZE_MB` | 20 | Upload size limit |

## Kubernetes

The `k8s/` manifests run the full stack on a local [k3d](https://k3d.io) cluster. They are plain Kubernetes; only the image names and the hostPath volumes are specific to k3d.

```powershell
.\k8s\start.ps1   # builds images, creates the cluster, deploys, opens http://localhost:8080
.\k8s\stop.ps1    # deletes the cluster; data stays in a Docker volume
```

- The frontend is a static Vite build served by nginx that calls the API on a relative `/api` path, so a single Ingress serves the whole app.
- Backend and frontend run with two replicas each, with startup, readiness and liveness probes and resource limits.
- PostgreSQL, Qdrant and Redis run as StatefulSets with persistent volumes.
- Port 8080 does not clash with Docker Compose, so both can run side by side.
- The committed `01-secrets.yaml` contains placeholders only; `start.ps1` patches the real keys from `.env` into the cluster Secret.

| Manifest | Contents |
|---|---|
| `00-namespace.yaml` | `docubrain` namespace |
| `01-secrets.yaml` | API keys and passwords (placeholders) |
| `02-configmap.yaml` | Non-sensitive backend config |
| `03-statefulsets.yaml` | PostgreSQL, Qdrant, Redis with volumes and headless Services |
| `04-deployments.yaml` | Backend and frontend Deployments |
| `05-services.yaml` | ClusterIP Services |
| `06-ingress.yaml` | `/api` and Swagger docs → backend, `/` → frontend |

## CI/CD

GitHub Actions ([`.github/workflows/main.yml`](../.github/workflows/main.yml)):

1. **Test** on every push and pull request to `main`, with a PostgreSQL service container.
2. **Build and push** on `main` only: backend and frontend images go to Docker Hub tagged with `latest` and the commit SHA, using the GitHub Actions build cache.

Required repository secrets: `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`, `GROQ_API_KEY`.
