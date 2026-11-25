"""Document ingestion and vector indexing service."""

import hashlib
import os
from pathlib import Path
import uuid
from typing import Optional
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.core.logging import get_logger
from backend.app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from backend.app.services.rag.chunker import chunk_text, extract_text_from_bytes
from backend.app.services.rag.embeddings import get_embedding_service

logger = get_logger("services.rag.ingestion")


class DocumentIngestionService:
    """Manages document text parsing, chunking, embedding generation and storage."""

    def __init__(self):
        self.embedding_service = get_embedding_service()

    async def ingest_document(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        title: str,
        file_bytes: bytes,
        filename: str,
        document_type: str = "general",
        department_id: Optional[uuid.UUID] = None,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
    ) -> KnowledgeDocument:
        """Parse, chunk, embed, and store a document with tenant isolation."""
        content_hash = hashlib.sha256(file_bytes).hexdigest()

        # Check if identical document already exists for this tenant
        stmt = select(KnowledgeDocument).where(
            KnowledgeDocument.org_id == org_id,
            KnowledgeDocument.content_hash == content_hash,
        )
        res = await db.execute(stmt)
        existing = res.scalars().first()
        if existing:
            logger.info("Document with hash %s already exists for tenant %s (doc_id=%s)", content_hash, org_id, existing.id)
            return existing

        # Store file on disk for persistent retry capability
        storage_dir = Path("backend/storage/documents") / str(org_id)
        storage_dir.mkdir(parents=True, exist_ok=True)
        import re
        safe_filename = re.sub(r"[^a-zA-Z0-9_.-]", "_", filename)
        file_disk_path = str(storage_dir / f"{content_hash[:12]}_{safe_filename}")
        try:
            with open(file_disk_path, "wb") as f:
                f.write(file_bytes)
        except Exception as e:
            logger.warning("Could not persist file to disk: %s", e)
            file_disk_path = filename

        # Extract text
        text = extract_text_from_bytes(file_bytes, filename)
        if not text.strip():
            raise ValueError(f"Document {filename} contains no extractable text.")

        # Chunk text
        chunks_data = chunk_text(text, chunk_size=chunk_size, overlap=chunk_overlap)
        if not chunks_data:
            chunks_data = [{
                "chunk_index": 0,
                "chunk_content": text.strip()[:chunk_size],
                "token_count": len(text.strip().split()),
            }]

        # Generate embeddings
        chunk_texts = [c["chunk_content"] for c in chunks_data]
        embeddings = await self.embedding_service.embed_documents(chunk_texts)

        # Create KnowledgeDocument
        doc = KnowledgeDocument(
            id=uuid.uuid4(),
            org_id=org_id,
            department_id=department_id,
            title=title,
            document_type=document_type,
            file_path=file_disk_path,
            content_hash=content_hash,
            chunk_count=len(chunks_data),
            is_active=True,
        )
        db.add(doc)
        await db.flush()

        # Create KnowledgeChunks
        for c_data, emb in zip(chunks_data, embeddings):
            chunk = KnowledgeChunk(
                id=uuid.uuid4(),
                org_id=org_id,
                document_id=doc.id,
                chunk_index=c_data["chunk_index"],
                chunk_content=c_data["chunk_content"],
                embedding=emb,
                token_count=c_data["token_count"],
            )
            db.add(chunk)

        await db.flush()
        logger.info("Successfully ingested document %s (%d chunks) for org %s", doc.id, len(chunks_data), org_id)
        return doc

    async def retry_document(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        document_id: uuid.UUID,
        new_file_bytes: Optional[bytes] = None,
        new_filename: Optional[str] = None,
    ) -> KnowledgeDocument:
        """Retry or re-index a document that failed processing or was deactivated."""
        stmt = select(KnowledgeDocument).where(
            KnowledgeDocument.id == document_id,
            KnowledgeDocument.org_id == org_id,
        )
        res = await db.execute(stmt)
        doc = res.scalars().first()
        if not doc:
            raise ValueError(f"Document {document_id} not found for this organization.")

        file_bytes = new_file_bytes
        filename = new_filename or (Path(doc.file_path).name if doc.file_path else "document.txt")

        # Load from disk if new bytes not supplied
        if not file_bytes and doc.file_path and os.path.exists(doc.file_path):
            with open(doc.file_path, "rb") as f:
                file_bytes = f.read()

        if not file_bytes:
            raise ValueError(f"No document source content available on disk to retry processing for document {document_id}.")

        text = extract_text_from_bytes(file_bytes, filename)
        if not text.strip():
            raise ValueError("Document contains no extractable text.")

        # Clear existing chunks
        await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id))

        # Re-chunk and embed
        chunks_data = chunk_text(text)
        chunk_texts = [c["chunk_content"] for c in chunks_data]
        embeddings = await self.embedding_service.embed_documents(chunk_texts)

        for c_data, emb in zip(chunks_data, embeddings):
            chunk = KnowledgeChunk(
                id=uuid.uuid4(),
                org_id=org_id,
                document_id=doc.id,
                chunk_index=c_data["chunk_index"],
                chunk_content=c_data["chunk_content"],
                embedding=emb,
                token_count=c_data["token_count"],
            )
            db.add(chunk)

        doc.chunk_count = len(chunks_data)
        doc.content_hash = hashlib.sha256(file_bytes).hexdigest()
        doc.is_active = True
        await db.flush()
        logger.info("Successfully retried document %s (%d chunks re-indexed)", doc.id, len(chunks_data))
        return doc

    async def ingest_raw_text(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        title: str,
        text_content: str,
        document_type: str = "general",
        department_id: Optional[uuid.UUID] = None,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
    ) -> KnowledgeDocument:
        """Directly ingest raw text (e.g. from structured FAQs or catalogue)."""
        file_bytes = text_content.encode("utf-8")
        return await self.ingest_document(
            db=db,
            org_id=org_id,
            title=title,
            file_bytes=file_bytes,
            filename=f"{title.lower().replace(' ', '_')}.txt",
            document_type=document_type,
            department_id=department_id,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    async def delete_document(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        document_id: uuid.UUID,
    ) -> bool:
        """Delete document and all associated chunks for a tenant."""
        stmt = select(KnowledgeDocument).where(
            KnowledgeDocument.id == document_id,
            KnowledgeDocument.org_id == org_id,
        )
        res = await db.execute(stmt)
        doc = res.scalars().first()
        if not doc:
            return False

        await db.delete(doc)
        await db.flush()
        logger.info("Deleted document %s for org %s", document_id, org_id)
        return True
