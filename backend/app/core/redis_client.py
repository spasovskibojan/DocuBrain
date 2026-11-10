import hashlib
import json
import logging
from typing import Any, Optional

import redis.asyncio as redis

from app.core.config import settings

logger = logging.getLogger(__name__)


class RedisClient:
    """
    Async Redis client wrapper.
    Handles connection lifecycle and provides typed cache operations.
    Every operation fails soft: if Redis is unreachable the app keeps working without it.
    """

    def __init__(self):
        self._client: Optional[redis.Redis] = None

    async def connect(self) -> None:
        self._client = redis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )

    async def disconnect(self) -> None:
        if self._client:
            await self._client.aclose()


    async def get_cached_query(
        self, question: str, user_id: str, document_id: Optional[str] = None
    ) -> Optional[dict]:
        """Return a previously cached answer, or None on cache miss / Redis failure."""
        try:
            key = await self._query_key(question, user_id, document_id)
            raw = await self._client.get(key)
            return json.loads(raw) if raw else None
        except Exception as e:
            logger.warning("Redis cache read failed: %s", e)
            return None

    async def set_cached_query(
        self, question: str, user_id: str, response: dict, document_id: Optional[str] = None
    ) -> None:
        """Cache an answer with the configured TTL."""
        try:
            key = await self._query_key(question, user_id, document_id)
            await self._client.setex(key, settings.CACHE_TTL_SECONDS, json.dumps(response))
        except Exception as e:
            logger.warning("Redis cache write failed: %s", e)

    async def invalidate_user_cache(self, user_id: str) -> None:
        """
        Invalidate all cached queries for a user (e.g. after uploading new docs).
        Bumping the version makes old keys unreachable; they expire on their own TTL.
        """
        try:
            await self._client.incr(self._version_key(user_id))
        except Exception as e:
            logger.warning("Redis cache invalidation failed: %s", e)


    async def hit_rate_limit(self, user_id: str, window_seconds: int) -> Optional[tuple[int, int]]:
        """
        Count one request in the user's current fixed window.
        Returns (request_count, seconds_until_reset), or None if Redis is unavailable.
        """
        key = f"docubrain:ratelimit:{user_id}"
        try:
            async with self._client.pipeline(transaction=True) as pipe:
                pipe.incr(key)
                pipe.expire(key, window_seconds, nx=True)
                pipe.ttl(key)
                count, _, ttl = await pipe.execute()
            return count, ttl if ttl > 0 else window_seconds
        except Exception as e:
            logger.warning("Redis rate limit check failed: %s", e)
            return None

    async def ping(self) -> bool:
        """Health check — returns True if Redis is reachable."""
        try:
            return await self._client.ping()
        except Exception:
            return False


    @staticmethod
    def _version_key(user_id: str) -> str:
        return f"docubrain:query_version:{user_id}"

    async def _query_key(self, question: str, user_id: str, document_id: Optional[str]) -> str:
        """
        Build a deterministic cache key from the question + user + document scope,
        namespaced by the user's cache version.
        Hashing the question keeps the key short and consistent.
        """
        version = await self._client.get(self._version_key(user_id)) or "0"
        question_hash = hashlib.sha256(
            f"{document_id or '*'}:{question.lower().strip()}".encode()
        ).hexdigest()[:16]
        return f"docubrain:query:{user_id}:v{version}:{question_hash}"


redis_client = RedisClient()
