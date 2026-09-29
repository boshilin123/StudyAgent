from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "StudyAgent API"
    app_env: Literal["development", "test", "production"] = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    api_prefix: str = "/api"
    log_level: str = "INFO"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    database_url: str = "postgresql+asyncpg://study_agent:change_me@localhost:5432/study_agent"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    milvus_uri: str = "http://localhost:19530"
    milvus_document_collection: str = "study_documents"
    milvus_question_collection: str = "study_questions"

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "change_me"
    minio_secret_key: str = "change_me"
    minio_bucket: str = "study-materials"
    minio_secure: bool = False
    storage_backend: Literal["local", "minio"] = "local"
    local_storage_path: str = "../../data/uploads"

    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_temperature: float = 0.1
    llm_timeout_seconds: float = 60.0
    llm_enable_thinking: bool = False
    llm_structured_output_method: Literal["parser", "function_calling", "json_schema"] = (
        "parser"
    )
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None
    embedding_model: str | None = None
    embedding_provider: Literal["local", "openai_compatible", "tei"] = "local"
    embedding_dimensions: int = 384
    embedding_timeout_seconds: float = 30.0

    chunk_size: int = 800
    chunk_overlap: int = 120
    ingestion_eager: bool = False
    question_generation_max_context_chars: int = 24000
    study_explanation_enabled: bool = True

    max_upload_size_mb: int = 100
    session_ttl_seconds: int = 7200


@lru_cache
def get_settings() -> Settings:
    return Settings()
