import asyncio, sys, os, uuid
sys.path.insert(0, os.path.abspath('.'))
from backend.app.core.config import settings
from backend.app.ai.conversation.orchestrator import ConversationOrchestrator
from backend.app.core.database import AsyncSessionLocal
from backend.app.models.organization import Organization
from backend.app.models.conversation import Conversation
from backend.app.models.message import Message
from sqlalchemy import select

async def test_4_messages():
    print("=== Testing 4 Customer Conversation Messages ===")
    print(f"Provider: {settings.DEFAULT_AI_PROVIDER}")
    print(f"Model: {settings.GEMINI_MODEL}")
    
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(Organization).where(Organization.slug == "fortisales-live-testing"))
        org = res.scalars().first()
        assert org is not None, "Live testing org not found"

        test_conv = Conversation(
            id=uuid.uuid4(),
            org_id=org.id,
            status="active",
            turn_count=1,
        )
        db.add(test_conv)
        # Pre-seed greeting
        greeting = Message(
            conversation_id=test_conv.id,
            turn_number=1,
            speaker_role="ai_agent",
            content="Hello! Thank you for calling FortiSales. Welcome! I'm your AI receptionist. May I know your name?",
        )
        db.add(greeting)
        await db.commit()
        await db.refresh(test_conv)

        test_inputs = [
            "My name is Sourav.",
            "I want to know about your products.",
            "What services do you provide?",
            "I want to speak with your sales team.",
        ]

        for i, user_text in enumerate(test_inputs, 1):
            print(f"\n--- Turn {i} ---")
            print(f"Customer: \"{user_text}\"")
            turn_res = await ConversationOrchestrator.handle_message(
                db=db,
                conversation_id=test_conv.id,
                org_id=org.id,
                user_message_text=user_text,
                provider=settings.DEFAULT_AI_PROVIDER,
                enable_ai_fallback=False, # Must NOT trigger technical difficulties fallback!
            )
            ai_text = turn_res.assistant_reply.content
            print(f"AI: \"{ai_text}\"")
            assert "technical difficulties" not in ai_text.lower(), f"Technical difficulties fallback triggered on turn {i}!"
            await asyncio.sleep(2.0)

        print("\n=== ALL 4 MESSAGES TESTED AND VERIFIED SUCCESSFULLY! ===")

if __name__ == "__main__":
    asyncio.run(test_4_messages())
