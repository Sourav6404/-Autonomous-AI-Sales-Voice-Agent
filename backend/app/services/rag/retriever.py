"""Tenant-isolated semantic retrieval engine powered by PostgreSQL pgvector."""

import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.core.logging import get_logger
from backend.app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from backend.app.services.rag.embeddings import get_embedding_service

logger = get_logger("services.rag.retriever")


@dataclass
class SearchResult:
    """Individual retrieved knowledge chunk with relevance score and metadata."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    document_type: str
    content: str
    score: float
    token_count: int


class KnowledgeRetriever:
    """Executes tenant-isolated vector similarity searches against PostgreSQL pgvector."""

    def __init__(self):
        self.embedding_service = get_embedding_service()

    async def search(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        query: str,
        limit: int = 4,
        score_threshold: float = 0.25,
        document_types: Optional[List[str]] = None,
    ) -> List[SearchResult]:
        """Search tenant knowledge base using cosine distance on pgvector HNSW/vector index."""
        if not query or not query.strip():
            return []

        query_vector = await self.embedding_service.embed_query(query)

        # pgvector cosine_distance returns value between 0 (identical) and 2 (opposite)
        # Cosine similarity = 1.0 - cosine_distance
        cosine_dist = KnowledgeChunk.embedding.cosine_distance(query_vector)

        stmt = (
            select(
                KnowledgeChunk.id,
                KnowledgeChunk.document_id,
                KnowledgeDocument.title,
                KnowledgeDocument.document_type,
                KnowledgeChunk.chunk_content,
                cosine_dist.label("distance"),
                KnowledgeChunk.token_count,
            )
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .where(
                KnowledgeChunk.org_id == org_id,
                KnowledgeDocument.org_id == org_id,
                KnowledgeDocument.is_active == True,
            )
        )

        if document_types:
            stmt = stmt.where(KnowledgeDocument.document_type.in_(document_types))

        stmt = stmt.order_by(cosine_dist.asc()).limit(limit * 2)

        result = await db.execute(stmt)
        rows = result.all()

        results: List[SearchResult] = []
        for row in rows:
            chunk_id, doc_id, doc_title, doc_type, content, distance, tokens = row
            # If distance is None (uninitialized or 0 norm), skip
            if distance is None:
                continue
            # Cosine similarity calculation: similarity = 1 - distance
            similarity = round(float(1.0 - distance), 4)

            # Filter below score threshold
            if similarity < score_threshold:
                continue

            results.append(
                SearchResult(
                    chunk_id=chunk_id,
                    document_id=doc_id,
                    document_title=doc_title,
                    document_type=doc_type,
                    content=content,
                    score=similarity,
                    token_count=tokens,
                )
            )

            if len(results) >= limit:
                break

        logger.info(
            "Retrieved %d knowledge results for query '%s' in org %s",
            len(results),
            query[:30],
            org_id,
        )
        return results
