from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "DocuBrain"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # No default on purpose: the app must not start with a key that is public in the repo
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    DATABASE_URL: str = "postgresql+asyncpg://docubrain_user:docubrain_secret@localhost:5432/docubrain"
    SYNC_DATABASE_URL: str = "postgresql+psycopg2://docubrain_user:docubrain_secret@localhost:5432/docubrain"

    REDIS_URL: str = "redis://:redis_secret@localhost:6379/0"
    CACHE_TTL_SECONDS: int = 3600  # 1 hour
    RATE_LIMIT_REQUESTS: int = 10
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    AUTH_RATE_LIMIT_REQUESTS: int = 10

    MAX_UPLOAD_SIZE_MB: int = 20

    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333

    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "openai/gpt-oss-20b"
    GROQ_ANSWER_MODEL: str = "openai/gpt-oss-120b"
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    RERANKER_MODEL: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # all-MiniLM-L6-v2 truncates input at 256 tokens (~1000 characters)
    CHUNK_SIZE: int = 900
    CHUNK_OVERLAP: int = 150
    TOP_K_RETRIEVAL: int = 50
    TOP_K_RERANK: int = 5
    RELEVANCE_THRESHOLD: float = -3.0
    MAX_QUERY_REWRITES: int = 1
    CHAT_HISTORY_TURNS: int = 3

    # Tracing is enabled only when both keys are set
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_BASE_URL: str = "https://cloud.langfuse.com"
    LANGFUSE_ENVIRONMENT: str = "development"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
