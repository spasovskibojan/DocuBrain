from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.redis_client import redis_client
from app.api.auth import router as auth_router
from app.api.documents import router as documents_router
from app.api.query import router as query_router
from app.api.workflows import router as workflows_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await redis_client.connect()
    print("✅ Connected to Redis")
    yield
    await redis_client.disconnect()
    print("🛑 Disconnected from Redis")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, change this to your actual frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api/auth", tags=["Authentication"])
app.include_router(documents_router, prefix="/api/documents", tags=["Documents"])
app.include_router(query_router, prefix="/api/query", tags=["AI Query"])
app.include_router(workflows_router, prefix="/api/workflows", tags=["Workflows"])

@app.get("/api/health", tags=["Health"])
async def health_check():
    """Health check endpoint to verify backend and Redis are running."""
    redis_healthy = await redis_client.ping()
    return {
        "status": "healthy",
        "redis_connected": redis_healthy,
        "version": settings.APP_VERSION,
    }
