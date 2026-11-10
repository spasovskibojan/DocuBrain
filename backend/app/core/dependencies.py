from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.redis_client import redis_client
from app.core.security import decode_access_token
from app.models.user import User

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """
    FastAPI dependency that validates the JWT and returns the authenticated User.
    Inject this into any route that requires authentication.
    """
    user_id = decode_access_token(credentials.credentials)

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or deactivated",
        )

    return user


async def rate_limit(
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    """
    Per-user fixed-window rate limit for AI endpoints.
    Fails open: if Redis is down, the request is allowed.
    """
    result = await redis_client.hit_rate_limit(
        current_user.id.hex, settings.RATE_LIMIT_WINDOW_SECONDS
    )
    if result is None:
        return

    count, retry_after = result
    if count > settings.RATE_LIMIT_REQUESTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Rate limit exceeded: {settings.RATE_LIMIT_REQUESTS} AI requests per "
                f"{settings.RATE_LIMIT_WINDOW_SECONDS}s. Try again in {retry_after}s."
            ),
            headers={"Retry-After": str(retry_after)},
        )
