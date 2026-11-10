import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine
from app.core.redis_client import redis_client
from app.api.auth import router as auth_router
from app.api.documents import router as documents_router
from app.api.query import router as query_router
from app.api.workflows import router as workflows_router


MIGRATION_LOCK_ID = 841_502


def _upgrade_to_head() -> None:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "alembic"))
    command.upgrade(config, "head")


async def run_migrations() -> None:
    # Advisory lock so parallel replicas don't migrate at the same time
    async with engine.connect() as conn:
        await conn.execute(text("SELECT pg_advisory_lock(:id)"), {"id": MIGRATION_LOCK_ID})
        try:
            await asyncio.to_thread(_upgrade_to_head)
        finally:
            await conn.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": MIGRATION_LOCK_ID})


@asynccontextmanager
async def lifespan(app: FastAPI):
    await run_migrations()
    await redis_client.connect()
    print("Connected to Redis")
    yield
    await redis_client.disconnect()
    print("Disconnected from Redis")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: restrict to the frontend domain in production
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
