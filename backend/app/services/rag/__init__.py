"""RAG services package for FortiSales AI."""

from backend.app.services.rag.embeddings import (
    BaseEmbeddingService,
    DeterministicSemanticEmbeddingService,
    OpenAIEmbeddingService,
    get_embedding_service,
)
from backend.app.services.rag.chunker import chunk_text, extract_text_from_bytes
from backend.app.services.rag.ingestion import DocumentIngestionService
from backend.app.services.rag.sync_service import KnowledgeSyncService
from backend.app.services.rag.retriever import KnowledgeRetriever, SearchResult

__all__ = [
    "BaseEmbeddingService",
    "DeterministicSemanticEmbeddingService",
    "OpenAIEmbeddingService",
    "get_embedding_service",
    "chunk_text",
    "extract_text_from_bytes",
    "DocumentIngestionService",
    "KnowledgeSyncService",
    "KnowledgeRetriever",
    "SearchResult",
]
