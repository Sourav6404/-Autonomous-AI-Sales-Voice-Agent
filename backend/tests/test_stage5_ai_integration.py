"""Stage 5 tests: AI Conversation Engine integration with Knowledge Base and RAG tools."""

import uuid
from decimal import Decimal
import pytest
import pytest_asyncio
from backend.app.ai.conversation.orchestrator import ConversationOrchestrator
from backend.app.ai.conversation.prompt_manager import PromptManager
from backend.app.ai.providers.base import ChatMessage, LLMResponse, ToolCall
from backend.app.ai.tools.initial_tools import (
    get_business_policy,
    get_faq_answer,
    get_product_or_service_details,
    query_knowledge_base,
    tool_registry,
)
from backend.app.ai.tools.registry import ToolExecutionContext
from backend.app.ai.tools.schemas import (
    GetBusinessPolicyInput,
    GetFAQAnswerInput,
    GetProductOrServiceDetailsInput,
    QueryKnowledgeBaseInput,
)
from backend.app.models.business_settings import BusinessSettings
from backend.app.models.catalog import ProductService
from backend.app.models.conversation import Conversation
from backend.app.models.faq import FAQ
from backend.app.models.organization import Organization
from backend.app.models.policy import BusinessPolicy
from backend.app.services.rag.sync_service import KnowledgeSyncService


@pytest_asyncio.fixture
async def knowledge_setup(db_session):
    """Sets up an organization with full catalogue, FAQs, and policies."""
    org_id = uuid.uuid4()
    org = Organization(id=org_id, name="Apex Medical Technologies", slug=f"apex-{org_id.hex[:6]}", is_active=True)
    db_session.add(org)

    settings = BusinessSettings(
        org_id=org_id,
        industry="Medical Devices & HealthTech",
        website="https://apexmed.tech",
        business_address="500 Health Way, Boston MA",
        contact_phone="+1-800-555-APEX",
        contact_email="care@apexmed.tech",
        company_overview="Apex provides FDA-cleared diagnostic scanning devices and AI diagnostics.",
        business_description="Innovative medical imaging and telehealth platforms.",
        business_services="Imaging system sales, annual maintenance contracts, remote clinical triage.",
        additional_info="All sales include a 1-year manufacturer warranty.",
    )
    db_session.add(settings)

    # Products with all 3 pricing types
    prod_fixed = ProductService(
        org_id=org_id,
        name="UltraScan Pro Handheld",
        description="Portable point-of-care ultrasound scanner.",
        category="Hardware",
        price=Decimal("4999.00"),
        currency="USD",
        pricing_type="fixed",
        is_available=True,
        features="Wireless probe, 8-hour battery",
    )
    prod_starting = ProductService(
        org_id=org_id,
        name="Clinical AI Analytics Suite",
        description="Cloud diagnostic triage and workflow acceleration.",
        category="Software",
        price=Decimal("250.00"),
        currency="USD",
        pricing_type="starting_from",
        is_available=True,
        features="PACS integration, real-time alerting",
    )
    prod_quote = ProductService(
        org_id=org_id,
        name="Hospital Enterprise PACS Deployment",
        description="Multi-facility on-premise imaging storage archive.",
        category="Enterprise",
        price=None,
        currency="USD",
        pricing_type="quotation_required",
        is_available=True,
    )
    db_session.add_all([prod_fixed, prod_starting, prod_quote])

    # FAQs
    faq = FAQ(
        org_id=org_id,
        question="How long does device delivery take after ordering?",
        answer="Standard shipping is 3 to 5 business days across North America. Expedited overnight delivery is available upon request.",
        category="Shipping",
        is_active=True,
    )
    db_session.add(faq)

    # Policies
    policy = BusinessPolicy(
        org_id=org_id,
        policy_type="cancellation",
        title="Software Subscription Cancellation Policy",
        content="Subscriptions may be cancelled with 30 days written notice before the annual renewal date.",
        is_active=True,
    )
    db_session.add(policy)

    # Conversation
    conv = Conversation(
        id=uuid.uuid4(),
        org_id=org_id,
        status="active",
    )
    db_session.add(conv)
    await db_session.commit()

    # Sync into RAG
    sync = KnowledgeSyncService()
    await sync.sync_company_info(db_session, org_id, org.name, settings)
    await sync.sync_product(db_session, prod_fixed)
    await sync.sync_product(db_session, prod_starting)
    await sync.sync_product(db_session, prod_quote)
    await sync.sync_faq(db_session, faq)
    await sync.sync_policy(db_session, policy)
    await db_session.commit()

    return {
        "org_id": org_id,
        "conversation_id": conv.id,
        "prod_fixed": prod_fixed,
        "prod_starting": prod_starting,
        "prod_quote": prod_quote,
        "faq": faq,
        "policy": policy,
    }


@pytest.mark.asyncio
async def test_product_catalogue_anti_hallucination_guidance(db_session, knowledge_setup):
    """Verify tool output enforces fixed vs starting vs quotation required pricing distinctions."""
    data = knowledge_setup
    ctx = ToolExecutionContext(
        db=db_session,
        org_id=data["org_id"],
        conversation_id=data["conversation_id"],
    )

    # 1. Fixed price product
    res_fixed = await get_product_or_service_details(
        GetProductOrServiceDetailsInput(name="UltraScan"),
        context=ctx,
    )
    assert res_fixed.found is True
    item_fixed = res_fixed.items[0]
    assert item_fixed.pricing_type == "fixed"
    assert "Confirmed price is 4999.00 USD" in item_fixed.pricing_guidance

    # 2. Starting from product
    res_starting = await get_product_or_service_details(
        GetProductOrServiceDetailsInput(name="Clinical AI"),
        context=ctx,
    )
    assert res_starting.found is True
    item_starting = res_starting.items[0]
    assert item_starting.pricing_type == "starting_from"
    assert "Price starts from 250.00 USD" in item_starting.pricing_guidance
    assert "indicative starting price" in item_starting.pricing_guidance

    # 3. Quotation required product
    res_quote = await get_product_or_service_details(
        GetProductOrServiceDetailsInput(name="Hospital Enterprise"),
        context=ctx,
    )
    assert res_quote.found is True
    item_quote = res_quote.items[0]
    assert item_quote.pricing_type == "quotation_required"
    assert "NEVER state or guess a price" in item_quote.pricing_guidance


@pytest.mark.asyncio
async def test_policy_and_faq_tools(db_session, knowledge_setup):
    """Verify get_business_policy and get_faq_answer retrieve verified data."""
    data = knowledge_setup
    ctx = ToolExecutionContext(
        db=db_session,
        org_id=data["org_id"],
        conversation_id=data["conversation_id"],
    )

    # FAQ tool
    faq_out = await get_faq_answer(
        GetFAQAnswerInput(query="delivery"),
        context=ctx,
    )
    assert faq_out.found is True
    assert "3 to 5 business days" in faq_out.items[0].answer

    # Policy tool
    policy_out = await get_business_policy(
        GetBusinessPolicyInput(policy_type="cancellation"),
        context=ctx,
    )
    assert policy_out.found is True
    assert "30 days written notice" in policy_out.policies[0].content


@pytest.mark.asyncio
async def test_prompt_manager_guardrails_injection(db_session, knowledge_setup):
    """Verify PromptManager dynamically injects business overview, industry, and anti-hallucination rules."""
    data = knowledge_setup
    prompt = await PromptManager.build_system_prompt(db_session, data["org_id"])

    assert "Apex Medical Technologies" in prompt
    assert "Medical Devices & HealthTech" in prompt
    assert "https://apexmed.tech" in prompt
    assert "PRICING RULES:" in prompt
    assert "Confirmed Fixed Prices" in prompt
    assert "Starting Prices" in prompt
    assert "Quotation Required" in prompt
    assert "query_knowledge_base" in prompt


@pytest.mark.asyncio
async def test_orchestrator_multi_turn_with_knowledge_tool(db_session, knowledge_setup):
    """Verify ConversationOrchestrator invokes knowledge tools when instructed by provider."""
    data = knowledge_setup

    class MockKnowledgeLLMProvider:
        """Simulates LLM that first invokes get_product_or_service_details, then answers."""
        def __init__(self):
            self.turn = 0

        async def generate_response(self, messages, tools=None, temperature=0.7, max_tokens=1024):
            self.turn += 1
            if self.turn == 1:
                return LLMResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="call_kb_123",
                            name="get_product_or_service_details",
                            arguments={"name": "UltraScan"},
                        )
                    ],
                    provider="mock",
                )
            return LLMResponse(
                content="The UltraScan Pro Handheld is available at a confirmed fixed price of 4,999.00 USD.",
                tool_calls=[],
                provider="mock",
            )

    provider = MockKnowledgeLLMProvider()
    result = await ConversationOrchestrator.handle_message(
        db=db_session,
        conversation_id=data["conversation_id"],
        org_id=data["org_id"],
        user_message_text="How much does the UltraScan cost?",
        provider=provider,
    )

    assert result.tool_calls_executed is not None
    assert len(result.tool_calls_executed) == 1
    assert result.tool_calls_executed[0]["tool"] == "get_product_or_service_details"
    assert "4,999.00 USD" in result.assistant_reply.content


@pytest.mark.asyncio
async def test_pricing_tool_precedence_in_prompt_and_registry(db_session, knowledge_setup):
    """Verify that structured product pricing retrieval takes precedence over loosely related vector results."""
    data = knowledge_setup

    # 1. Check tool descriptions in registry
    product_tool = tool_registry.get_tool("get_product_or_service_details")
    kb_tool = tool_registry.get_tool("query_knowledge_base")

    assert product_tool is not None
    assert "Use this tool first whenever a customer asks about products, services, or pricing" in product_tool["description"]

    assert kb_tool is not None
    assert "prefer 'get_product_or_service_details'" in kb_tool["description"]

    # 2. Check PromptManager anti-hallucination instructions
    prompt = await PromptManager.build_system_prompt(db_session, data["org_id"])
    assert "Confirmed structured product pricing ALWAYS takes precedence over loosely related vector text chunks" in prompt
