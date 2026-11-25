"""Stage 5 tests: Document chunking, embeddings, and vector similarity retrieval."""

import socket
import uuid
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from backend.app.core.config import settings
from backend.app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from backend.app.models.organization import Organization
from backend.app.services.rag.chunker import chunk_text, extract_text_from_bytes
from backend.app.services.rag.embeddings import DeterministicSemanticEmbeddingService, EMBEDDING_DIM
from backend.app.services.rag.ingestion import DocumentIngestionService
from backend.app.services.rag.retriever import KnowledgeRetriever


def is_live_postgres_available() -> bool:
    if "postgresql" not in settings.async_database_url:
        return False
    try:
        sock = socket.create_connection((settings.POSTGRES_SERVER, settings.POSTGRES_PORT), timeout=1.0)
        sock.close()
        return True
    except (OSError, ConnectionRefusedError):
        return False


POSTGRES_ONLINE = is_live_postgres_available()


def test_chunker_sliding_window_and_boundaries():
    """Verify semantic text chunker splits long paragraphs with correct window and overlap."""
    sample_text = (
        "Paragraph One: FortiSales AI provides automated voice receptionist systems for enterprises.\n\n"
        "Paragraph Two: The system answers telephone calls using ultra-low latency speech-to-text models. "
        "It understands intent and schedules appointments directly in the business calendar. "
        "Customers can cancel or reschedule appointments with 24 hours advance notice.\n\n"
        "Paragraph Three: All audio can be recorded with explicit consent. Voice data is encrypted in transit and at rest."
    )
    chunks = chunk_text(sample_text, chunk_size=120, overlap=20)
    assert len(chunks) >= 2
    for c in chunks:
        assert len(c["chunk_content"]) > 0
        assert c["token_count"] > 0
        assert "chunk_index" in c


def test_fitz_pdf_extraction_in_memory():
    """Verify PyMuPDF (fitz) extracts text cleanly from an in-memory synthetic PDF stream."""
    import fitz

    # Create a simple PDF in memory
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 72), "FortiSales AI Enterprise Knowledge Base Test Page")
    page.insert_text((50, 100), "Our refund policy requires 48 hours notice prior to appointment.")
    pdf_bytes = doc.tobytes()
    doc.close()

    extracted = extract_text_from_bytes(pdf_bytes, filename="test_doc.pdf")
    assert "Enterprise Knowledge Base Test Page" in extracted
    assert "refund policy" in extracted


def test_docx_extraction_in_memory():
    """Verify python-docx extracts paragraphs and tables from in-memory DOCX stream."""
    import io
    import docx

    doc = docx.Document()
    doc.add_heading("Enterprise Service Level Agreement", level=1)
    doc.add_paragraph("All premium subscribers receive dedicated 24/7 technical assistance.")
    
    # Add a table
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Tier"
    table.cell(0, 1).text = "Response Time"
    table.cell(1, 0).text = "Gold"
    table.cell(1, 1).text = "15 minutes"

    buf = io.BytesIO()
    doc.save(buf)
    docx_bytes = buf.getvalue()

    extracted = extract_text_from_bytes(docx_bytes, filename="sla_document.docx")
    assert "Enterprise Service Level Agreement" in extracted
    assert "dedicated 24/7 technical assistance" in extracted
    assert "Gold | 15 minutes" in extracted


def test_production_mock_embedding_fails_closed(monkeypatch):
    """Verify that deterministic mock embeddings fail closed in production environment."""
    from backend.app.services.rag import embeddings as emb_module

    # Reset cached singleton
    monkeypatch.setattr(emb_module, "_embedding_instance", None)
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")

    with pytest.raises(RuntimeError) as exc_info:
        emb_module.get_embedding_service()
    assert "strictly forbidden in production" in str(exc_info.value)


@pytest.mark.asyncio
async def test_deterministic_semantic_embeddings():
    """Verify 384-dimensional normalized vectors and positive cosine similarity for semantically aligned text."""
    service = DeterministicSemanticEmbeddingService()
    assert service.dimension == EMBEDDING_DIM

    query = "cancellation and refund policy"
    related_doc = "our refund policy requires 24 hours advance notice for appointment cancellation"
    unrelated_doc = "quantum physics and nuclear magnetic resonance spectrometry"

    q_vec = await service.embed_query(query)
    rel_vecs = await service.embed_documents([related_doc, unrelated_doc])
    rel_vec, unrel_vec = rel_vecs[0], rel_vecs[1]

    # Verify dimensionality
    assert len(q_vec) == 384
    assert len(rel_vec) == 384
    assert len(unrel_vec) == 384

    # Verify L2 normalization (norm ~ 1.0)
    norm_q = sum(x * x for x in q_vec) ** 0.5
    assert abs(norm_q - 1.0) < 0.01

    # Cosine similarity = dot product of unit vectors
    sim_related = sum(a * b for a, b in zip(q_vec, rel_vec))
    sim_unrelated = sum(a * b for a, b in zip(q_vec, unrel_vec))

    # Semantically overlapping texts must score significantly higher
    assert sim_related > 0.4
    assert sim_related > sim_unrelated


@pytest.mark.skipif(not POSTGRES_ONLINE, reason="Live PostgreSQL container required for pgvector index tests.")
@pytest.mark.asyncio
async def test_pgvector_live_retrieval_and_tenant_isolation():
    """Executes live vector similarity search against PostgreSQL 16 container with pgvector."""
    engine = create_async_engine(settings.async_database_url, echo=False)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    org_a_id = uuid.uuid4()
    org_b_id = uuid.uuid4()

    async with session_factory() as db:
        # Create organizations
        db.add_all([
            Organization(id=org_a_id, name="Tenant A Corp", slug=f"t-a-{org_a_id.hex[:6]}", is_active=True),
            Organization(id=org_b_id, name="Tenant B Corp", slug=f"t-b-{org_b_id.hex[:6]}", is_active=True),
        ])
        await db.commit()

        ingestion = DocumentIngestionService()

        # Ingest Tenant A policy
        doc_a = await ingestion.ingest_raw_text(
            db=db,
            org_id=org_a_id,
            title="Tenant A Cancellation Terms",
            text_content="All dental consultations cancelled within 12 hours incur a 40 dollar late fee.",
            document_type="policy",
        )

        # Ingest Tenant B policy
        doc_b = await ingestion.ingest_raw_text(
            db=db,
            org_id=org_b_id,
            title="Tenant B VIP Warranty",
            text_content="All automotive repairs are covered under a lifetime comprehensive warranty.",
            document_type="policy",
        )
        await db.commit()

        # Query Tenant A with semantic retriever
        retriever = KnowledgeRetriever()
        results_a = await retriever.search(
            db=db,
            org_id=org_a_id,
            query="cancellation late fee",
            limit=3,
            score_threshold=0.2,
        )

        # Tenant A must find its own document
        assert len(results_a) >= 1
        assert "late fee" in results_a[0].content
        assert results_a[0].document_title == "Tenant A Cancellation Terms"

        # Cross-tenant check: Tenant A search must NEVER return Tenant B's warranty
        results_cross = await retriever.search(
            db=db,
            org_id=org_a_id,
            query="automotive repair lifetime warranty",
            limit=3,
            score_threshold=0.1,
        )
        for r in results_cross:
            assert "automotive" not in r.content
            assert r.document_title != "Tenant B VIP Warranty"

        # Cleanup
        await ingestion.delete_document(db, org_a_id, doc_a.id)
        await ingestion.delete_document(db, org_b_id, doc_b.id)
        await db.commit()

    await engine.dispose()
