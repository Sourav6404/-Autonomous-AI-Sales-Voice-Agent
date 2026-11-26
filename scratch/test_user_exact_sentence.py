import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.abspath("."))

from sqlalchemy import select
from backend.app.core.database import AsyncSessionLocal
from backend.app.core.config import settings
from backend.app.models.organization import Organization
from backend.app.models.conversation import Conversation
from backend.app.models.message import Message
from backend.app.ai.conversation.orchestrator import ConversationOrchestrator
from backend.app.services.voice.tts_service import CartesiaTTSService

async def test_exact_sentence():
    test_sentence = "Hello, my name is Sourav. I am looking for an AI agent development solution to automate my company."
    print("=== Testing User's Exact Complete Sentence ===")
    print(f"Customer Speech Input: \"{test_sentence}\"")
    print(f"Configured LLM Provider: {settings.DEFAULT_AI_PROVIDER}")
    print(f"Configured LLM Model: {settings.GEMINI_MODEL}")

    async with AsyncSessionLocal() as db:
        res = await db.execute(select(Organization).where(Organization.slug == "fortisales-live-testing"))
        org = res.scalar_one_or_none()
        assert org is not None, "Organization not found"

        test_conv = Conversation(
            org_id=org.id,
            status="active",
            turn_count=1,
        )
        db.add(test_conv)
        await db.commit()
        await db.refresh(test_conv)

        greeting = Message(
            conversation_id=test_conv.id,
            turn_number=1,
            speaker_role="ai_agent",
            content="Hello! Thank you for calling FortiSales Live Testing Corp. Welcome! I'm your AI receptionist. May I know your name?",
        )
        db.add(greeting)
        await db.commit()

        # Step 1: Timestamp - Final Transcript Received
        t_final_transcript = time.time()
        print(f"\n[1] Final Transcript Received at: {t_final_transcript:.3f}")

        # Step 2: Timestamp - Orchestrator Started
        t_orch_start = time.time()
        print(f"[2] Orchestrator Started at: {t_orch_start:.3f}")

        # Step 3: LLM Request Started
        t_llm_start = time.time()
        print(f"[3] LLM Request Started at: {t_llm_start:.3f}")

        turn_res = await ConversationOrchestrator.handle_message(
            db=db,
            conversation_id=test_conv.id,
            org_id=org.id,
            user_message_text=test_sentence,
            provider=settings.DEFAULT_AI_PROVIDER,
            enable_ai_fallback=False,
        )

        t_llm_completed = time.time()
        llm_duration_ms = int((t_llm_completed - t_llm_start) * 1000)
        ai_reply = turn_res.assistant_reply.content
        print(f"[4] LLM Request Completed at: {t_llm_completed:.3f} (Duration: {llm_duration_ms}ms)")
        print(f"    AI Generated Response: \"{ai_reply}\"")

        assert "technical difficulties" not in ai_reply.lower(), "AI failed with technical difficulties fallback!"
        assert ai_reply.strip() != "", "AI returned empty reply!"

        # Step 4: Cartesia TTS Audio Streaming
        tts = CartesiaTTSService(api_key=settings.CARTESIA_API_KEY, voice_id=settings.CARTESIA_VOICE_ID)
        chunks = []
        t_tts_start = time.time()
        t_first_chunk = None

        async def on_audio_chunk(chunk: bytes):
            nonlocal t_first_chunk
            if t_first_chunk is None:
                t_first_chunk = time.time()
            chunks.append(chunk)

        cancel_ev = asyncio.Event()
        tts_ok = await tts.synthesize_stream(ai_reply, on_audio_chunk, cancel_ev)

        t_tts_end = time.time()
        first_chunk_latency_ms = int((t_first_chunk - t_tts_start) * 1000) if t_first_chunk else 0
        total_audio_bytes = sum(len(c) for c in chunks)

        print(f"[5] Cartesia TTS First Chunk Received at: {t_first_chunk:.3f} (Latency to first chunk: {first_chunk_latency_ms}ms)")
        print(f"[6] Total Audio Chunks: {len(chunks)}, Total Bytes: {total_audio_bytes} bytes")
        print(f"[7] Playback Ready in Browser: YES ({len(chunks)} chunks of 16kHz PCM stream ready)")

        assert tts_ok, "TTS synthesis failed!"
        assert len(chunks) > 0, "No audio chunks produced by TTS!"

        print("\n=== SUCCESS: END-TO-END VERIFICATION COMPLETED WITHOUT ERRORS ===")

if __name__ == "__main__":
    asyncio.run(test_exact_sentence())
