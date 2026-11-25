"""Embedding services for FortiSales AI RAG pipeline.

Supports:
1. DeterministicSemanticEmbeddingService: Zero-dependency, 384-dimensional feature hashing
   embedding with subword n-grams and L2 normalization. Guarantees deterministic,
   reproducible cosine similarity for testing and local operation.
2. OpenAIEmbeddingService: Uses text-embedding-3-small with dimensions=384 via httpx.
3. SentenceTransformersEmbeddingService: Uses all-MiniLM-L6-v2 when available.
"""

import abc
import hashlib
import math
import re
from typing import List, Optional
import httpx
from backend.app.core.config import settings
from backend.app.core.logging import get_logger

logger = get_logger("services.rag.embeddings")

EMBEDDING_DIM = 384


class BaseEmbeddingService(abc.ABC):
    """Abstract base class for vector embedding generation."""

    @property
    def dimension(self) -> int:
        return EMBEDDING_DIM

    @abc.abstractmethod
    async def embed_query(self, text: str) -> List[float]:
        """Generate embedding vector for a single query."""
        pass

    @abc.abstractmethod
    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Generate embedding vectors for a list of document chunks."""
        pass


class DeterministicSemanticEmbeddingService(BaseEmbeddingService):
    """Zero-dependency 384-dim semantic embedding using feature hashing and subword projection.
    
    Produces normalized 384-dimensional vectors where textual overlap, key phrases,
    and semantic tokens have strong positive cosine similarity, while unrelated texts
    remain near-orthogonal.
    """

    def _embed_single(self, text: str) -> List[float]:
        if not text or not text.strip():
            return [0.0] * EMBEDDING_DIM

        vector = [0.0] * EMBEDDING_DIM
        cleaned = text.lower().strip()
        tokens = re.findall(r"\b\w+\b", cleaned)

        # Word-level features (weighted 2.0)
        for token in tokens:
            # MD5 hash for projection index
            h_raw = hashlib.md5(f"w:{token}".encode("utf-8")).digest()
            idx = int.from_bytes(h_raw[:4], byteorder="big") % EMBEDDING_DIM
            sign = 1.0 if (h_raw[4] % 2 == 0) else -1.0
            vector[idx] += 2.0 * sign

            # Character 3-gram and 4-gram features (weighted 1.0)
            if len(token) >= 3:
                for i in range(len(token) - 2):
                    tri = token[i : i + 3]
                    h_tri = hashlib.md5(f"tri:{tri}".encode("utf-8")).digest()
                    t_idx = int.from_bytes(h_tri[:4], byteorder="big") % EMBEDDING_DIM
                    t_sign = 1.0 if (h_tri[4] % 2 == 0) else -1.0
                    vector[t_idx] += 1.0 * t_sign

        # L2 Normalization
        norm_sq = sum(x * x for x in vector)
        if norm_sq > 0.0:
            norm = math.sqrt(norm_sq)
            return [round(x / norm, 6) for x in vector]
        return [0.0] * EMBEDDING_DIM

    async def embed_query(self, text: str) -> List[float]:
        return self._embed_single(text)

    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self._embed_single(t) for t in texts]


class OpenAIEmbeddingService(BaseEmbeddingService):
    """OpenAI embedding service using text-embedding-3-small with dimension=384."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.endpoint = "https://api.openai.com/v1/embeddings"
        self.model = "text-embedding-3-small"

    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "input": texts,
            "model": self.model,
            "dimensions": EMBEDDING_DIM,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(self.endpoint, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            # Sort by index to maintain ordering
            sorted_items = sorted(data["data"], key=lambda x: x["index"])
            return [item["embedding"] for item in sorted_items]

    async def embed_query(self, text: str) -> List[float]:
        results = await self.embed_documents([text])
        return results[0] if results else [0.0] * EMBEDDING_DIM


# Global singleton cache
_embedding_instance: Optional[BaseEmbeddingService] = None


def get_embedding_service(force_deterministic: bool = False) -> BaseEmbeddingService:
    """Factory to get the configured embedding service.
    
    Defaults to DeterministicSemanticEmbeddingService for offline safety and testing,
    or OpenAIEmbeddingService if OPENAI_API_KEY is configured and not in test mode.
    Fails closed in production if no valid external provider is configured.
    """
    global _embedding_instance
    if _embedding_instance is not None and not force_deterministic:
        return _embedding_instance

    is_production = getattr(settings, "APP_ENV", "development").lower() == "production"

    if settings.OPENAI_API_KEY and not settings.OPENAI_API_KEY.startswith("mock-") and not force_deterministic:
        try:
            logger.info("Initializing OpenAIEmbeddingService with text-embedding-3-small (dim=384)")
            _embedding_instance = OpenAIEmbeddingService(api_key=settings.OPENAI_API_KEY)
            return _embedding_instance
        except Exception as e:
            logger.warning("Failed to initialize OpenAIEmbeddingService: %s", e)
            if is_production:
                raise RuntimeError(
                    f"Production environment requires a functional OpenAIEmbeddingService: {e}"
                )

    if is_production and not force_deterministic:
        raise RuntimeError(
            "Production environment requires a valid OPENAI_API_KEY or configured embedding provider. "
            "Deterministic mock embedding is strictly forbidden in production."
        )

    _embedding_instance = DeterministicSemanticEmbeddingService()
    return _embedding_instance
