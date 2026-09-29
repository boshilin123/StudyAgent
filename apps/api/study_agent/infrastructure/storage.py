import shutil
from functools import partial
from pathlib import Path, PurePosixPath
from typing import BinaryIO

import anyio
from minio import Minio

from study_agent.domain.models import StoredObject


class LocalObjectStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, object_name: str) -> Path:
        normalized = PurePosixPath(object_name)
        if normalized.is_absolute() or ".." in normalized.parts:
            raise ValueError("invalid object name")
        target = (self.root / Path(*normalized.parts)).resolve()
        if self.root not in target.parents and target != self.root:
            raise ValueError("object path escapes storage root")
        return target

    async def put(
        self,
        *,
        object_name: str,
        stream: BinaryIO,
        size: int,
        content_type: str,
    ) -> StoredObject:
        del size, content_type
        target = self._resolve(object_name)
        await anyio.to_thread.run_sync(target.parent.mkdir, 0o777, True, True)
        stream.seek(0)
        with target.open("wb") as destination:
            await anyio.to_thread.run_sync(shutil.copyfileobj, stream, destination)
        return StoredObject(uri=f"local://{object_name}", object_name=object_name)

    async def delete(self, uri: str) -> None:
        prefix = "local://"
        if not uri.startswith(prefix):
            raise ValueError("invalid local storage URI")
        target = self._resolve(uri.removeprefix(prefix))
        if target.exists():
            await anyio.to_thread.run_sync(target.unlink)

    async def read(self, uri: str) -> bytes:
        prefix = "local://"
        if not uri.startswith(prefix):
            raise ValueError("invalid local storage URI")
        target = self._resolve(uri.removeprefix(prefix))
        return await anyio.to_thread.run_sync(target.read_bytes)


class MinioObjectStorage:
    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool,
    ) -> None:
        self.client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
        self.bucket = bucket

    async def _ensure_bucket(self) -> None:
        exists = await anyio.to_thread.run_sync(self.client.bucket_exists, self.bucket)
        if not exists:
            await anyio.to_thread.run_sync(self.client.make_bucket, self.bucket)

    async def put(
        self,
        *,
        object_name: str,
        stream: BinaryIO,
        size: int,
        content_type: str,
    ) -> StoredObject:
        await self._ensure_bucket()
        stream.seek(0)
        upload = partial(
            self.client.put_object,
            self.bucket,
            object_name,
            stream,
            size,
            content_type=content_type,
        )
        await anyio.to_thread.run_sync(upload)
        return StoredObject(uri=f"minio://{self.bucket}/{object_name}", object_name=object_name)

    async def delete(self, uri: str) -> None:
        prefix = f"minio://{self.bucket}/"
        if not uri.startswith(prefix):
            raise ValueError("invalid MinIO storage URI")
        await anyio.to_thread.run_sync(
            self.client.remove_object, self.bucket, uri.removeprefix(prefix)
        )

    async def read(self, uri: str) -> bytes:
        prefix = f"minio://{self.bucket}/"
        if not uri.startswith(prefix):
            raise ValueError("invalid MinIO storage URI")

        def download() -> bytes:
            response = self.client.get_object(self.bucket, uri.removeprefix(prefix))
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()

        return await anyio.to_thread.run_sync(download)
