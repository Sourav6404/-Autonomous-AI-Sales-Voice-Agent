import asyncio
import os
import json
import httpx
from backend.app.core.config import settings
from backend.app.ai.providers.openai_provider import OpenAIProvider
from backend.app.ai.providers.base import ChatMessage
from backend.app.services.rag.embeddings import get_embedding_service, OpenAIEmbeddingService, DeterministicSemanticEmbeddingService
from backend.app.services.voice.tts_service import CartesiaTTSService, MockTTSService

async def test_openai_direct():
    print("--- 1. Testing OpenAI LLM (gpt-4o-mini) ---")
    if not settings.OPENAI_API_KEY:
        print("FAIL: OPENAI_API_KEY is not set.")
        return False
    
    provider = OpenAIProvider(api_key=settings.OPENAI_API_KEY, model="gpt-4o-mini")
    try:
        messages = [
            ChatMessage(role="system", content="You are a helpful assistant. Reply in exactly one sentence containing the word 'Antigravity'."),
            ChatMessage(role="user", content="Say hello and identify yourself.")
        ]
        response = await provider.generate_response(messages=messages, temperature=0.1)
        print("OpenAI Status: SUCCESS")
        print("Model used:", response.model)
        print("Provider:", response.provider)
        print("Response Content:", response.content)
        print("Usage Tokens:", response.usage)
        assert "Antigravity" in response.content, f"Expected 'Antigravity' in response: {response.content}"
        assert response.provider == "openai"
        return True
    except Exception as e:
        print(f"OpenAI LLM Failed: {type(e).__name__}: {e}")
        return False

async def test_embedding():
    print("\n--- 2. Testing Embedding Service ---")
    emb_service = get_embedding_service()
    print("Embedding Service Class:", emb_service.__class__.__name__)
    
    # Test OpenAIEmbeddingService directly
    if settings.OPENAI_API_KEY:
        openai_emb = OpenAIEmbeddingService(api_key=settings.OPENAI_API_KEY)
        try:
            vec = await openai_emb.embed_query("Apex Nexus Robotics warranty policy")
            print("OpenAIEmbeddingService call: SUCCESS")
            print(f"Vector length: {len(vec)} (Expected: 384)")
            print("Sample vector slice:", [round(x, 4) for x in vec[:5]])
            return True, emb_service.__class__.__name__
        except Exception as e:
            print(f"OpenAIEmbeddingService failed: {type(e).__name__}: {e}")
            return False, emb_service.__class__.__name__
    return False, emb_service.__class__.__name__

async def test_cartesia():
    print("\n--- 3. Testing Cartesia TTS ---")
    if not settings.CARTESIA_API_KEY:
        print("Cartesia API Key: Not configured (Mock mode active)")
        return False, "Not configured"
    
    tts = CartesiaTTSService(api_key=settings.CARTESIA_API_KEY)
    try:
        chunks = []
        async for audio_chunk in tts.synthesize_stream("Hello from FortiSales AI receptionist."):
            chunks.append(audio_chunk)
        total_bytes = sum(len(c) for c in chunks)
        print(f"Cartesia TTS call: SUCCESS ({len(chunks)} chunks, {total_bytes} bytes received)")
        return True, "Active"
    except Exception as e:
        print(f"Cartesia TTS failed: {type(e).__name__}: {e}")
        return False, f"Failed: {e}"

async def main():
    llm_ok = await test_openai_direct()
    emb_ok, emb_name = await test_embedding()
    cartesia_ok, cartesia_status = await test_cartesia()
    
    print("\n=== SUMMARY ===")
    print(f"LLM (gpt-4o-mini): {'PASS' if llm_ok else 'FAIL'}")
    print(f"Embedding Service: {'PASS' if emb_ok else 'FAIL'} (Active: {emb_name})")
    print(f"Cartesia TTS: {'PASS' if cartesia_ok else 'BLOCKED/FAIL'} (Status: {cartesia_status})")

if __name__ == "__main__":
    asyncio.run(main())
