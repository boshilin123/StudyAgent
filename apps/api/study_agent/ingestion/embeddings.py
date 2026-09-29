import hashlib
import math
import re
from typing import Any

import httpx
from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings
from pydantic import SecretStr

from study_agent.config import Settings


class DeterministicEmbeddings(Embeddings):
    """无需外部模型的开发回退，不用于衡量生产检索质量。"""

    def __init__(self, dimensions: int = 384) -> None:
        self.dimensions = dimensions

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        normalized = re.sub(r"\s+", " ", text.lower()).strip()
        features = re.findall(r"[a-z0-9_]+|[\u3400-\u9fff]", normalized)
        features.extend(
            normalized[index : index + 3] for index in range(max(0, len(normalized) - 2))
        )
        for feature in features:
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[bucket] += sign
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class TeiEmbeddings(Embeddings):
    """Hugging Face Text Embeddings Inference `/embed` 适配器。"""

    def __init__(self, endpoint: str, timeout: float = 30.0) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout

    def _request(self, texts: list[str]) -> list[list[float]]:
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(f"{self.endpoint}/embed", json={"inputs": texts})
            response.raise_for_status()
        payload: Any = response.json()
        if not isinstance(payload, list) or len(payload) != len(texts):
            raise ValueError("TEI 返回的向量数量与输入文本数量不一致")
        vectors: list[list[float]] = []
        for item in payload:
            if not isinstance(item, list) or not item:
                raise ValueError("TEI 返回了无效向量")
            vectors.append([float(value) for value in item])
        return vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._request(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._request([text])[0]


def build_embeddings(settings: Settings) -> tuple[Embeddings, str]:
    if settings.embedding_provider == "tei":
        if not settings.embedding_base_url:
            raise ValueError("使用 TEI 时必须配置 EMBEDDING_BASE_URL")
        return (
            TeiEmbeddings(settings.embedding_base_url, settings.embedding_timeout_seconds),
            settings.embedding_model or "tei",
        )
    if settings.embedding_provider == "openai_compatible":
        if not settings.embedding_base_url or not settings.embedding_model:
            raise ValueError(
                "使用 OpenAI-compatible Embedding 时必须配置 EMBEDDING_BASE_URL 和 EMBEDDING_MODEL"
            )
        return (
            OpenAIEmbeddings(
                base_url=settings.embedding_base_url,
                api_key=SecretStr(settings.embedding_api_key or "not-required"),
                model=settings.embedding_model,
                dimensions=settings.embedding_dimensions,
                timeout=settings.embedding_timeout_seconds,
                # 百炼的 OpenAI-compatible 工作空间端点要求 input 为字符串数组，
                # 不接受 LangChain 长文本安全模式生成的 token ID 数组。
                check_embedding_ctx_length=False,
                # text-embedding-v4 当前单次最多接收 10 条文本。
                chunk_size=10,
            ),
            settings.embedding_model,
        )
    return DeterministicEmbeddings(settings.embedding_dimensions), "deterministic-local-v1"
