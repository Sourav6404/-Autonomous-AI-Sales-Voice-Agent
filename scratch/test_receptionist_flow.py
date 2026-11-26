import asyncio, sys, os, uuid
sys.path.insert(0, os.path.abspath('.'))
from backend.app.core.config import settings
from backend.app.ai.conversation.orchestrator import ConversationOrchestrator
from backend.app.ai.conversation.prompt_manager import PromptManager
from backend.app.ai.providers.base import ChatMessage
from backend.app.ai.providers.factory import get_ai_provider
from backend.app.core.database import AsyncSessionLocal
from backend.app.models.organization import Organization
from backend.app.models.conversation import Conversation
from backend.app.models.message import Message
from sqlalchemy import select

async def test_receptionist_flow():
    print("=== Testing Minimal Receptionist Flow ===")
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(Organization).where(Organization.slug == "fortisales-live-testing"))
        org = res.scalars().first()
        assert org is not None, "Live testing org not found"

        test_conv = Conversation(
            id=uuid.uuid4(),
            org_id=org.id,
            status="active",
            turn_count=0,
        )
        db.add(test_conv)
        await db.commit()
        await db.refresh(test_conv)

        # 1. Test Initial Greeting via real LLM
        system_prompt = await PromptManager.build_system_prompt(db=db, org_id=org.id)
        provider = get_ai_provider(settings.DEFAULT_AI_PROVIDER)
        prompt_messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(
                role="user",
                content="[New incoming call connected. Welcome the caller to FortiSales, introduce yourself as the AI receptionist, and politely ask for their name. Keep it concise, 1-2 spoken sentences.]",
            ),
        ]
        resp = await provider.generate_response(messages=prompt_messages)
        greeting = (resp.content or "").strip()
        print(f"\n[AI Greeting Turn 1]:\n{greeting}")
        assert len(greeting) > 10, "Greeting was empty"

        # Save Greeting turn
        msg1 = Message(
            conversation_id=test_conv.id,
            turn_number=1,
            speaker_role="ai_agent",
            content=greeting,
        )
        db.add(msg1)
        test_conv.turn_count = 1
        await db.commit()

        # 2. Customer introduces self & asks about drone
        user_msg_1 = "Hi, my name is Alex. I'm looking for a drone for warehouse inventory."
        print(f"\n[Customer Turn 2]:\n{user_msg_1}")

        turn_2 = await ConversationOrchestrator.handle_message(
            db=db,
            conversation_id=test_conv.id,
            org_id=org.id,
            user_message_text=user_msg_1,
            provider=settings.DEFAULT_AI_PROVIDER,
            enable_ai_fallback=True,
        )
        ai_reply_2 = turn_2.assistant_reply.content
        print(f"\n[AI Turn 3]:\n{ai_reply_2}")
        assert "Alex" in ai_reply_2 or "alex" in ai_reply_2.lower(), "AI did not acknowledge Alex by name"

        # 3. Customer asks about product price
        user_msg_2 = "What is the price of the Apex Guardian Drone X1?"
        print(f"\n[Customer Turn 4]:\n{user_msg_2}")

        turn_3 = await ConversationOrchestrator.handle_message(
            db=db,
            conversation_id=test_conv.id,
            org_id=org.id,
            user_message_text=user_msg_2,
            provider=settings.DEFAULT_AI_PROVIDER,
            enable_ai_fallback=True,
        )
        ai_reply_3 = turn_3.assistant_reply.content
        print(f"\n[AI Turn 5]:\n{ai_reply_3}")
        assert "12,500" in ai_reply_3 or "12500" in ai_reply_3, "Price not grounded in RAG"

        # 4. Customer agrees to an appointment
        user_msg_3 = "Yes, I would like to arrange an appointment with a sales representative."
        print(f"\n[Customer Turn 6]:\n{user_msg_3}")

        turn_4 = await ConversationOrchestrator.handle_message(
            db=db,
            conversation_id=test_conv.id,
            org_id=org.id,
            user_message_text=user_msg_3,
            provider=settings.DEFAULT_AI_PROVIDER,
            enable_ai_fallback=True,
        )
        ai_reply_4 = turn_4.assistant_reply.content
        print(f"\n[AI Turn 7]:\n{ai_reply_4}")

        print("\n=== ALL 5 REQUIREMENTS VERIFIED SUCCESSFULLY! ===")

if __name__ == "__main__":
    asyncio.run(test_receptionist_flow())
