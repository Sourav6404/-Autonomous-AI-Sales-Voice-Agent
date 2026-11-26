import asyncio, sys, os, uuid
sys.path.insert(0, os.path.abspath('.'))
from backend.app.core.config import settings
from backend.app.ai.conversation.orchestrator import ConversationOrchestrator
from backend.app.core.database import AsyncSessionLocal
from backend.app.models.organization import Organization
from backend.app.models.conversation import Conversation
from backend.app.services.voice.tts_service import get_tts_service, SentenceAggregator
from sqlalchemy import select

async def test_full_pipeline():
    print("=== Testing End-to-End Pipeline ===")
    print(f"LLM Provider: {settings.DEFAULT_AI_PROVIDER}")
    print(f"TTS Provider: {settings.TTS_PROVIDER}")
    print(f"Cartesia Model: {settings.CARTESIA_MODEL}")
    print(f"Cartesia Voice ID: {settings.CARTESIA_VOICE_ID}")
    
    # 1. Database & Org
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(Organization).where(Organization.slug == "fortisales-live-testing"))
        org = res.scalars().first()
        
        test_conv = Conversation(
            id=uuid.uuid4(),
            org_id=org.id,
            status="active",
        )
        db.add(test_conv)
        await db.commit()
        await db.refresh(test_conv)

        # 2. Customer question
        user_question = "What is the price of the Apex Guardian Drone X1?"
        print(f"1. Customer Question: '{user_question}'")

        # 3. Gemini Orchestrator + RAG
        turn_response = await ConversationOrchestrator.handle_message(
            db=db,
            conversation_id=test_conv.id,
            org_id=org.id,
            user_message_text=user_question,
            provider=settings.DEFAULT_AI_PROVIDER,
            enable_ai_fallback=True,
        )
        ai_reply = turn_response.assistant_reply.content
        print(f"2. Gemini RAG Response: '{ai_reply}'")

        # 4. Cartesia TTS Synthesis
        aggregator = SentenceAggregator()
        sentences = aggregator.feed_token(ai_reply)
        sentences.extend(aggregator.flush())
        if not sentences:
            sentences = [ai_reply]

        tts_service = get_tts_service()
        print(f"3. Synthesizing {len(sentences)} sentence(s) with {tts_service.__class__.__name__}...")
        
        total_audio_chunks = 0
        total_audio_bytes = 0
        async def on_audio_chunk(chunk: bytes):
            nonlocal total_audio_chunks, total_audio_bytes
            total_audio_chunks += 1
            total_audio_bytes += len(chunk)

        cancellation_event = asyncio.Event()
        for idx, sentence in enumerate(sentences):
            success = await tts_service.synthesize_stream(
                text=sentence,
                on_audio_chunk=on_audio_chunk,
                cancellation_event=cancellation_event,
            )
            print(f"   Sentence {idx+1} [{'OK' if success else 'FAILED'}]: '{sentence}'")

        print(f"4. TTS Result: Synthesized {total_audio_chunks} chunks ({total_audio_bytes} bytes of 16kHz PCM audio)")
        assert total_audio_bytes > 0, "No audio synthesized!"
        print("=== FULL PIPELINE VERIFIED SUCCESSFULLY! ===")

if __name__ == "__main__":
    asyncio.run(test_full_pipeline())
