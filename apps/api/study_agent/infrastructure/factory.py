from functools import lru_cache
from pathlib import Path

from study_agent.config import get_settings
from study_agent.domain.ports import ObjectStorage
from study_agent.infrastructure.storage import LocalObjectStorage, MinioObjectStorage


@lru_cache
def get_storage() -> ObjectStorage:
    settings = get_settings()
    if settings.storage_backend == "minio":
        return MinioObjectStorage(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            bucket=settings.minio_bucket,
            secure=settings.minio_secure,
        )
    return LocalObjectStorage(Path(settings.local_storage_path))
