import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.database import engine
from main import app, run_migrations


@pytest_asyncio.fixture
async def client():
    # ASGITransport skips the lifespan, so the schema is migrated here
    await run_migrations()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    # Each test runs in its own event loop; pooled connections can't be reused across loops
    await engine.dispose()
