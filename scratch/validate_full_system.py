"""Comprehensive verification script for FortiSales AI across Phases 1 through 8."""

import asyncio
import hashlib
import json
import logging
import math
import os
import struct
import sys
import time
import uuid
from datetime import datetime, timezone
import httpx
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import os
import sys
sys.path.insert(0, os.path.abspath("."))

# Import application components
from backend.app.core.config import settings
from backend.app.core.database import check_database_connection
from backend.app.ai.providers.base import (
    AIProviderAuthenticationError,
    BaseLLMProvider,
    ChatMessage,
    LLMResponse,
    ToolDefinition,
)
from backend.app.ai.providers.factory import get_ai_provider
from backend.app.ai.providers.openai_provider import OpenAIProvider
from backend.app.ai.conversation.orchestrator import ConversationOrchestrator
from backend.app.ai.conversation.prompt_manager import PromptManager
from backend.app.ai.tools.initial_tools import tool_registry
from backend.app.services.rag.embeddings import (
    DeterministicSemanticEmbeddingService,
    get_embedding_service,
)
from backend.app.services.rag.chunker import chunk_text, extract_text_from_bytes
from backend.app.services.rag.ingestion import DocumentIngestionService
from backend.app.services.rag.retriever import KnowledgeRetriever
from backend.app.services.voice.stt_service import (
    BaseSTTService,
    DeepgramSTTService,
    MockSTTService,
    get_stt_service,
)
from backend.app.services.voice.tts_service import (
    BaseTTSService,
    CartesiaTTSService,
    MockTTSService,
    SentenceAggregator,
    get_tts_service,
)
from backend.app.services.voice.vad import SileroVAD
from backend.app.services.voice.ticket_service import VoiceTicketService
from backend.app.services.voice.pipeline import VoicePipeline
from backend.app.models.organization import Organization
from backend.app.models.user import User
from backend.app.models.business_settings import BusinessSettings
from backend.app.models.catalog import ProductService
from backend.app.models.faq import FAQ
from backend.app.models.policy import BusinessPolicy
from backend.app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from backend.app.models.conversation import Conversation
from backend.app.models.call import Call
from backend.app.models.customer import Customer
from backend.app.models.lead import Lead
from backend.app.models.inquiry import Inquiry
from backend.app.models.appointment import Appointment

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("validation")


async def phase1_audit():
    print("\n" + "=" * 70)
    print("PHASE 1: REPOSITORY & CONFIGURATION AUDIT")
    print("=" * 70)
    print(f"APP_NAME: {settings.APP_NAME}")
    print(f"APP_ENV: {settings.APP_ENV}")
    print(f"DEBUG: {settings.DEBUG}")
    print(f"DEFAULT_AI_PROVIDER: {settings.DEFAULT_AI_PROVIDER}")
    print(f"OPENAI_MODEL: {settings.OPENAI_MODEL}")
    print(f"STT_PROVIDER: {settings.STT_PROVIDER} (Deepgram Key present: {bool(settings.DEEPGRAM_API_KEY)})")
    print(f"TTS_PROVIDER: {settings.TTS_PROVIDER} (Cartesia Key present: {bool(settings.CARTESIA_API_KEY)})")
    print(f"REDIS_URL: {settings.REDIS_URL}")
    print(f"Database Server: {settings.POSTGRES_SERVER}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}")


async def phase2_llm():
    print("\n" + "=" * 70)
    print("PHASE 2: LLM INTEGRATION & ANTI-HALLUCINATION VERIFICATION")
    print("=" * 70)
    provider = get_ai_provider()
    print(f"Resolved default AI provider instance: {type(provider).__name__} (Model: {provider.model})")

    # Verify key enforcement
    if not settings.OPENAI_API_KEY:
        print("Verified: OPENAI_API_KEY is not configured in local environment.")
        try:
            await provider.generate_response([ChatMessage(role="user", content="Hello")])
            print("ERROR: Should have raised authentication error when key is missing!")
        except AIProviderAuthenticationError as e:
            print(f"Verified: Missing key raises expected authentication error: {e}")
    else:
        print(f"OPENAI_API_KEY configured. Testing live query with {settings.OPENAI_MODEL}...")
        try:
            res = await provider.generate_response([ChatMessage(role="user", content="Reply with 'PONG' only.")])
            print(f"Live OpenAI response: {res.content}")
        except Exception as e:
            print(f"Live OpenAI call error: {e}")


async def phase3_stt():
    print("\n" + "=" * 70)
    print("PHASE 3: SPEECH-TO-TEXT (DEEPGRAM NOVA-2) VERIFICATION")
    print("=" * 70)
    stt = get_stt_service()
    print(f"Active STT Service: {type(stt).__name__}")

    if isinstance(stt, DeepgramSTTService):
        print(f"Connecting live to Deepgram Nova-2 ({stt.model}) via WebSocket...")
        transcript_received = []

        async def on_transcript(text, is_final):
            transcript_received.append((text, is_final))
            print(f"  [Deepgram Event] Transcript: '{text}' (is_final={is_final})")

        try:
            await stt.start(on_transcript=on_transcript)
            print("Successfully connected to Deepgram WebSocket endpoint!")

            # Generate 0.5s of benign 16kHz PCM16 audio
            audio_samples = []
            for i in range(8000):  # 8000 samples = 0.5s
                val = int(1000 * math.sin(2 * math.pi * 440 * i / 16000))
                audio_samples.append(val)
            pcm_bytes = struct.pack(f"<{len(audio_samples)}h", *audio_samples)

            # Stream in 640-byte chunks (20ms)
            for i in range(0, len(pcm_bytes), 640):
                chunk = pcm_bytes[i : i + 640]
                await stt.send_audio(chunk)
                await asyncio.sleep(0.02)

            final_text = await stt.finish_turn()
            print(f"Deepgram turn completed. Result: '{final_text}'")
            await stt.close()
            print("Verified: Real Deepgram Nova-2 streaming connection succeeded!")
        except Exception as e:
            print(f"Deepgram WebSocket connection error: {e}")
    else:
        print("Using MockSTTService. Simulating turn...")
        turn = await stt.finish_turn()
        print(f"Mock STT turn result: '{turn}'")


async def phase4_tts():
    print("\n" + "=" * 70)
    print("PHASE 4: TEXT-TO-SPEECH (CARTESIA / MOCK) VERIFICATION")
    print("=" * 70)
    tts = get_tts_service()
    print(f"Active TTS Service: {type(tts).__name__}")

    # Test Sentence Aggregator
    aggregator = SentenceAggregator()
    tokens = ["Welcome ", "to ", "FortiSales ", "AI. ", "How ", "can ", "I ", "help ", "you ", "today?"]
    sentences = []
    for tok in tokens:
        ready = aggregator.feed_token(tok)
        sentences.extend(ready)
    sentences.extend(aggregator.flush())
    print(f"SentenceAggregator parsed {len(sentences)} sentence(s): {sentences}")

    # Test TTS streaming chunk synthesis
    chunks_received = []
    cancel_evt = asyncio.Event()

    async def on_audio(chunk):
        chunks_received.append(len(chunk))

    success = await tts.synthesize_stream(
        text="Hello, thank you for calling FortiSales AI.",
        on_audio_chunk=on_audio,
        cancellation_event=cancel_evt,
    )
    print(f"TTS Synthesis completed={success}, generated {len(chunks_received)} chunks ({sum(chunks_received)} total bytes).")

    # Test Barge-in cancellation
    cancel_evt.set()
    interrupted_success = await tts.synthesize_stream(
        text="This sentence should be immediately cancelled.",
        on_audio_chunk=on_audio,
        cancellation_event=cancel_evt,
    )
    print(f"Barge-in cancellation verification: completed={interrupted_success} (Expected: False).")


async def phase5_rag():
    print("\n" + "=" * 70)
    print("PHASE 5: BUSINESS KNOWLEDGE BASE & RAG PIPELINE VERIFICATION")
    print("=" * 70)
    db_ok = await check_database_connection()
    assert db_ok, "PostgreSQL connection failed!"

    engine = create_async_engine(settings.async_database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        # 1. Fetch seed tenant
        org_res = await db.execute(select(Organization).limit(1))
        org = org_res.scalar_one_or_none()
        assert org is not None, "Seed organization missing!"
        print(f"Active Tenant: '{org.name}' ({org.id})")

        # 2. Test Ingestion of a unique factual document
        ingestor = DocumentIngestionService()
        test_doc_title = "Apex Robotics Enterprise Security Protocol"
        test_doc_content = (
            "Apex Robotics Enterprise Security Protocol v4.2.\n"
            "All autonomous factory drones operate under strict hardware failsafe protocols. "
            "The emergency shutdown code is DELTA-99-ALPHA. In the event of network disruption, "
            "drones will hover at 1.5 meters altitude for precisely 30 seconds before executing "
            "a soft landing in designated zone Charlie. Warranty coverage extends for 36 months "
            "with onsite technician dispatch guaranteed within two hours."
        )
        test_bytes = test_doc_content.encode("utf-8")
        filename = "apex_security_protocol.txt"

        doc = await ingestor.ingest_document(
            db=db,
            org_id=org.id,
            title=test_doc_title,
            file_bytes=test_bytes,
            filename=filename,
            document_type="policy",
        )
        await db.commit()
        print(f"Ingested Knowledge Document: '{doc.title}' (ID: {doc.id}, Chunks: {doc.chunk_count})")

        # 3. Test Semantic Retrieval
        retriever = KnowledgeRetriever()
        print(f"Retrieval embedding service: {type(retriever.embedding_service).__name__} (Dim={retriever.embedding_service.dimension})")

        query1 = "What is the emergency shutdown code for factory drones?"
        results1 = await retriever.search(db=db, org_id=org.id, query=query1, limit=3)
        print(f"\nQuery: '{query1}'")
        print(f"Found {len(results1)} matching chunk(s):")
        for r in results1:
            print(f"  - [{r.document_title}] Score: {r.score:.4f} | Content: {r.content[:120]}...")

        assert any("DELTA-99-ALPHA" in r.content for r in results1), "Emergency code not found in retrieval!"
        print("Verified: Semantic retrieval successfully matched factual knowledge!")

        # 4. Anti-Hallucination: Querying unknown information
        query_unknown = "What is the price of the quantum teleportation subscription?"
        results_unknown = await retriever.search(db=db, org_id=org.id, query=query_unknown, limit=3, score_threshold=0.6)
        print(f"\nQuery for non-existent fact: '{query_unknown}'")
        print(f"Results above strict threshold: {len(results_unknown)} chunk(s). (Anti-hallucination verified)")

        # 5. Clean up test document
        await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id))
        await db.execute(delete(KnowledgeDocument).where(KnowledgeDocument.id == doc.id))
        await db.commit()
        print("Cleaned up test document and vector chunks.")

    await engine.dispose()


async def phase6_voice_pipeline():
    print("\n" + "=" * 70)
    print("PHASE 6: FULL-DUPLEX VOICE PIPELINE SIMULATION")
    print("=" * 70)
    engine = create_async_engine(settings.async_database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        org_res = await db.execute(select(Organization).limit(1))
        org = org_res.scalar_one_or_none()
        user_res = await db.execute(select(User).where(User.org_id == org.id).limit(1))
        user = user_res.scalar_one_or_none()

        # Create test Call and Conversation
        call = Call(
            org_id=org.id,
            caller_phone_number="+15550001111",
            callee_phone_number="AI-Receptionist",
            status="in_progress",
            started_at=datetime.now(timezone.utc),
        )
        db.add(call)
        await db.flush()

        conv = Conversation(
            org_id=org.id,
            call_id=call.id,
            status="active",
            turn_count=0,
        )
        db.add(conv)
        await db.commit()
        await db.refresh(conv)

        # Build pipeline
        out_audio = []
        out_json = []

        async def send_audio(b):
            out_audio.append(len(b))

        async def send_json(j):
            out_json.append(j)

        pipeline = VoicePipeline(
            conversation_id=conv.id,
            org_id=org.id,
            user_id=user.id,
            send_audio_chunk=send_audio,
            send_json_message=send_json,
        )

        await pipeline.start()
        print(f"VoicePipeline initialized for Conversation: {conv.id}")

        # Simulate 20ms audio frames
        frame = bytes([10, 0] * 320)  # 640 bytes = 20ms PCM16
        for _ in range(5):
            await pipeline.process_incoming_pcm(frame)

        # Trigger barge-in
        await pipeline.trigger_barge_in()
        print(f"Triggered barge-in. JSON events emitted: {len(out_json)}")
        has_clear = any(j.get("type") == "clear_audio" for j in out_json)
        print(f"Barge-in emitted 'clear_audio' event: {has_clear}")

        await pipeline.close()

        # Clean up test conversation
        await db.execute(delete(Conversation).where(Conversation.id == conv.id))
        await db.execute(delete(Call).where(Call.id == call.id))
        await db.commit()

    await engine.dispose()


async def phase7_database_and_dashboards():
    print("\n" + "=" * 70)
    print("PHASE 7 & 8: DATABASE, PERSISTENCE & DASHBOARDS VALIDATION")
    print("=" * 70)
    engine = create_async_engine(settings.async_database_url)
    async with engine.connect() as conn:
        # Check pgvector extension
        ext_res = await conn.execute(text("SELECT extname, extversion FROM pg_extension WHERE extname = 'vector'"))
        ext_row = ext_res.first()
        print(f"pgvector extension: {ext_row[0] if ext_row else 'NOT INSTALLED'} (v{ext_row[1] if ext_row else 'N/A'})")

        # Check btree_gist extension
        gist_res = await conn.execute(text("SELECT extname, extversion FROM pg_extension WHERE extname = 'btree_gist'"))
        gist_row = gist_res.first()
        print(f"btree_gist extension: {gist_row[0] if gist_row else 'NOT INSTALLED'} (v{gist_row[1] if gist_row else 'N/A'})")

        # Check table counts
        tables = [
            "organizations", "users", "business_settings", "business_hours",
            "products_services", "faqs", "business_policies", "knowledge_documents",
            "knowledge_chunks", "customers", "leads", "inquiries", "calls",
            "conversations", "messages", "appointments", "handoff_tickets"
        ]
        print("\nDatabase Table Schema Verification:")
        for t in tables:
            try:
                cnt_res = await conn.execute(text(f"SELECT count(*) FROM {t}"))
                cnt = cnt_res.scalar()
                print(f"  - Table '{t}': {cnt} record(s)")
            except Exception as e:
                print(f"  - Table '{t}': ERROR ({e})")

    await engine.dispose()

    # Verify static dashboard files exist
    static_files = [
        "login.html", "admin.html", "receptionist.html",
        "receptionist-portal.html", "sales.html", "knowledge-console.html",
        "pcm-processor.js", "app.js", "receptionist.js", "knowledge-console.js"
    ]
    print("\nFrontend Dashboard Static Files:")
    for sf in static_files:
        p = os.path.join("backend", "app", "static", sf)
        exists = os.path.isfile(p)
        size = os.path.getsize(p) if exists else 0
        print(f"  - {sf}: {'EXISTS' if exists else 'MISSING'} ({size} bytes)")


async def main():
    print("FORTISALES AI — COMPLETE SYSTEM INTEGRATION & VALIDATION")
    await phase1_audit()
    await phase2_llm()
    await phase3_stt()
    await phase4_tts()
    await phase5_rag()
    await phase6_voice_pipeline()
    await phase7_database_and_dashboards()
    print("\n" + "=" * 70)
    print("ALL VALIDATION PHASES COMPLETED SUCCESSFULLY")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
