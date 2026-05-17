import hashlib
import json
from typing import Any, Optional

import redis.asyncio as redis

from app.core.config import settings


class RedisClient:
    """
    Async Redis client wrapper.
    Handles connection lifecycle and provides typed cache operations.
    """

    def __init__(self):
        self._client: Optional[redis.Redis] = None

    async def connect(self) -> None:
        self._client = redis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()

    # ── Query Cache ────────────────────────────────────────────────────────────

    async def get_cached_query(self, question: str, user_id: str) -> Optional[dict]:
        """Return a previously cached answer, or None on cache miss."""
        key = self._query_key(question, user_id)
        raw = await self._client.get(key)
        return json.loads(raw) if raw else None

    async def set_cached_query(self, question: str, user_id: str, response: dict) -> None:
        """Cache an answer with the configured TTL."""
        key = self._query_key(question, user_id)
        await self._client.setex(key, settings.CACHE_TTL_SECONDS, json.dumps(response))

    async def invalidate_user_cache(self, user_id: str) -> None:
        """Delete all cached queries for a user (e.g. after uploading new docs)."""
        pattern = f"docubrain:query:{user_id}:*"
        keys = await self._client.keys(pattern)
        if keys:
            await self._client.delete(*keys)

    async def ping(self) -> bool:
        """Health check — returns True if Redis is reachable."""
        try:
            return await self._client.ping()
        except Exception:
            return False

    # ── Key Builder ────────────────────────────────────────────────────────────

    @staticmethod
    def _query_key(question: str, user_id: str) -> str:
        """
        Build a deterministic cache key from the question + user.
        Hashing the question keeps the key short and consistent.
        """
        question_hash = hashlib.sha256(
            question.lower().strip().encode()
        ).hexdigest()[:16]
        return f"docubrain:query:{user_id}:{question_hash}"


# Singleton — shared across the whole app
redis_client = RedisClient()
