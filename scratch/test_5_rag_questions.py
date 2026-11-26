import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath("."))

from sqlalchemy import select
from backend.app.core.database import AsyncSessionLocal
from backend.app.core.config import settings
from backend.app.models.organization import Organization
from backend.app.models.conversation import Conversation
from backend.app.models.message import Message
from backend.app.ai.conversation.orchestrator import ConversationOrchestrator

async def test_5_rag_questions():
    print("=== Testing 5 RAG & Conversation Questions ===")
    print(f"Provider: {settings.DEFAULT_AI_PROVIDER}")
    print(f"Model: {settings.GEMINI_MODEL}")

    async with AsyncSessionLocal() as db:
        res = await db.execute(select(Organization).where(Organization.slug == "fortisales-live-testing"))
        org = res.scalar_one_or_none()
        assert org is not None, "Organization fortisales-live-testing not found!"

        # Create a clean conversation session
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

        test_inputs = [
            "My name is Sourav.",
            "What products do you offer?",
            "What is the price of your first product?",
            "What are your business hours?",
            "Can I book a product demonstration?",
        ]

        for i, user_text in enumerate(test_inputs, 1):
            print(f"\n--- Question {i} ---")
            print(f"Customer: \"{user_text}\"")
            turn_res = await ConversationOrchestrator.handle_message(
                db=db,
                conversation_id=test_conv.id,
                org_id=org.id,
                user_message_text=user_text,
                provider=settings.DEFAULT_AI_PROVIDER,
                enable_ai_fallback=False,
            )
            ai_text = turn_res.assistant_reply.content
            print(f"AI: \"{ai_text}\"")
            assert "technical difficulties" not in ai_text.lower(), f"Technical difficulties fallback on question {i}!"
            await asyncio.sleep(2.0)

        print("\n=== ALL 5 QUESTIONS TESTED AND VERIFIED SUCCESSFULLY! ===")

if __name__ == "__main__":
    asyncio.run(test_5_rag_questions())
