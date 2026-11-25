"""Knowledge base source documents and vectorized semantic chunks."""

import uuid
from typing import List, Optional
from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.app.models.base import GUID, Base, TenantMixin, TimestampMixin, VectorType


class KnowledgeDocument(Base, TenantMixin, TimestampMixin):
    """Source business knowledge document (PDF, TXT, FAQ, Pricing)."""

    __tablename__ = "knowledge_documents"
    __table_args__ = (
        CheckConstraint(
            "document_type IN ('faq', 'product_spec', 'pricing', 'policy', 'general')",
            name="ck_knowledge_docs_valid_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    department_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        GUID(), ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    document_type: Mapped[str] = mapped_column(String(50), default="general", nullable=False)
    file_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    chunks: Mapped[List["KnowledgeChunk"]] = relationship(
        "KnowledgeChunk", back_populates="document", cascade="all, delete-orphan"
    )


class KnowledgeChunk(Base, TenantMixin, TimestampMixin):
    """Vectorized semantic passage for RAG retrieval."""

    __tablename__ = "knowledge_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[List[float]] = mapped_column(VectorType(dim=384), nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships
    document: Mapped["KnowledgeDocument"] = relationship("KnowledgeDocument", back_populates="chunks")
