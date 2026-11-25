"""Safe, demonstrable initial tools for sales receptionist conversations."""

import logging
from sqlalchemy import select

from backend.app.ai.tools.registry import ToolExecutionContext, tool_registry
from backend.app.ai.tools.schemas import (
    AIAvailabilityOutput,
    BusinessHoursOutput,
    BusinessInformationOutput,
    BusinessPolicyOutput,
    FAQAnswerOutput,
    FAQItem,
    GetAIAvailabilityInput,
    GetBusinessHoursInput,
    GetBusinessInformationInput,
    GetBusinessPolicyInput,
    GetFAQAnswerInput,
    GetProductOrServiceDetailsInput,
    HumanHandoffOutput,
    PolicyItem,
    ProductOrServiceDetailsOutput,
    ProductOrServiceItem,
    QueryKnowledgeBaseInput,
    QueryKnowledgeBaseOutput,
    RequestHumanHandoffInput,
    WeekdayHourDetail,
)
from backend.app.models.business_hours import BusinessHours
from backend.app.models.business_settings import BusinessSettings
from backend.app.models.catalog import ProductService
from backend.app.models.conversation import Conversation
from backend.app.models.faq import FAQ
from backend.app.models.organization import Organization
from backend.app.models.policy import BusinessPolicy
from backend.app.services.availability_service import AvailabilityService
from backend.app.services.rag.retriever import KnowledgeRetriever

logger = logging.getLogger(__name__)

DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]


@tool_registry.register(
    name="get_business_information",
    description="Retrieve company profile, services, contact telephone, email, and address.",
    input_schema=GetBusinessInformationInput,
)
async def get_business_information(
    args: GetBusinessInformationInput,
    context: ToolExecutionContext,
) -> BusinessInformationOutput:
    """Fetches verified organization and business settings for the active tenant."""
    # 1. Fetch organization
    org_res = await context.db.execute(
        select(Organization).where(Organization.id == context.org_id)
    )
    org = org_res.scalar_one_or_none()
    org_name = org.name if org else "FortiSales AI Client"
    tz = org.default_timezone if org else "UTC"

    # 2. Fetch business settings
    settings_res = await context.db.execute(
        select(BusinessSettings).where(BusinessSettings.org_id == context.org_id)
    )
    settings = settings_res.scalar_one_or_none()

    return BusinessInformationOutput(
        name=org_name,
        description=settings.business_description if settings else None,
        services=settings.business_services if settings else None,
        contact_phone=settings.contact_phone if settings else None,
        contact_email=settings.contact_email if settings else None,
        address=settings.business_address if settings else None,
        timezone=tz,
    )


@tool_registry.register(
    name="get_business_hours",
    description="Retrieve weekly operating schedule and opening/closing hours.",
    input_schema=GetBusinessHoursInput,
)
async def get_business_hours(
    args: GetBusinessHoursInput,
    context: ToolExecutionContext,
) -> BusinessHoursOutput:
    """Fetches weekly operating hours scoped to current tenant."""
    org_res = await context.db.execute(
        select(Organization).where(Organization.id == context.org_id)
    )
    org = org_res.scalar_one_or_none()
    tz = org.default_timezone if org else "UTC"

    query = select(BusinessHours).where(BusinessHours.org_id == context.org_id)
    if args.day_of_week is not None:
        query = query.where(BusinessHours.day_of_week == args.day_of_week)
    query = query.order_by(BusinessHours.day_of_week, BusinessHours.open_time)

    res = await context.db.execute(query)
    entries = res.scalars().all()

    schedules = []
    for e in entries:
        day_name = DAY_NAMES[e.day_of_week] if 0 <= e.day_of_week <= 6 else f"Day {e.day_of_week}"
        schedules.append(
            WeekdayHourDetail(
                day=day_name,
                day_number=e.day_of_week,
                open_time=str(e.open_time),
                close_time=str(e.close_time),
                is_closed=e.is_closed,
            )
        )

    return BusinessHoursOutput(timezone=tz, schedules=schedules)


@tool_registry.register(
    name="get_ai_availability",
    description="Check real-time business open/closed status, AI receptionist availability, and upcoming schedule changes.",
    input_schema=GetAIAvailabilityInput,
)
async def get_ai_availability(
    args: GetAIAvailabilityInput,
    context: ToolExecutionContext,
) -> AIAvailabilityOutput:
    """Executes centralized availability precedence resolution for current tenant."""
    status_resp = await AvailabilityService.resolve_availability(
        db=context.db,
        org_id=context.org_id,
        department_id=args.department_id,
    )

    return AIAvailabilityOutput(
        business_status=status_resp.business_status,
        ai_status=status_resp.ai_status,
        reason=status_resp.reason,
        current_time=status_resp.current_time.isoformat(),
        timezone=status_resp.timezone,
        next_status_change=status_resp.next_status_change_at.isoformat() if status_resp.next_status_change_at else None,
    )


@tool_registry.register(
    name="request_human_handoff",
    description="Safely escalate conversation to a live human representative or schedule an urgent callback.",
    input_schema=RequestHumanHandoffInput,
)
async def request_human_handoff(
    args: RequestHumanHandoffInput,
    context: ToolExecutionContext,
) -> HumanHandoffOutput:
    """Signals handoff on conversation session without destructive database writes."""
    conv_res = await context.db.execute(
        select(Conversation).where(
            Conversation.id == context.conversation_id,
            Conversation.org_id == context.org_id,
        )
    )
    conv = conv_res.scalar_one_or_none()
    if conv:
        conv.status = "handed_off"

    ticket_id = f"ESC-{str(context.conversation_id)[:8].upper()}"
    return HumanHandoffOutput(
        handoff_status="queued",
        message="Your request has been escalated to a live representative. A team member has been notified.",
        ticket_reference=ticket_id,
    )


# ===========================================================================
# Stage 5 Tools: Knowledge Base, Catalogue, Policies, and FAQs
# ===========================================================================
_knowledge_retriever = KnowledgeRetriever()


@tool_registry.register(
    name="query_knowledge_base",
    description="Retrieve factual knowledge, company documents, specifications, or policies via semantic vector search. For specific product catalogue, offerings, or pricing inquiries, prefer 'get_product_or_service_details'.",
    input_schema=QueryKnowledgeBaseInput,
)
async def query_knowledge_base(
    args: QueryKnowledgeBaseInput,
    context: ToolExecutionContext,
) -> QueryKnowledgeBaseOutput:
    """Performs tenant-isolated vector search across knowledge base chunks."""
    doc_types = [args.document_type] if args.document_type else None
    results = await _knowledge_retriever.search(
        db=context.db,
        org_id=context.org_id,
        query=args.query,
        limit=3,
        document_types=doc_types,
    )

    if not results:
        return QueryKnowledgeBaseOutput(
            found=False,
            count=0,
            chunks=[],
            summary="No relevant knowledge base records matched the query.",
        )

    chunk_dicts = [
        {
            "document_title": r.document_title,
            "document_type": r.document_type,
            "content": r.content,
            "relevance_score": r.score,
        }
        for r in results
    ]

    summary_lines = [f"[{r.document_title}]: {r.content}" for r in results]
    return QueryKnowledgeBaseOutput(
        found=True,
        count=len(results),
        chunks=chunk_dicts,
        summary="\n---\n".join(summary_lines),
    )


@tool_registry.register(
    name="get_product_or_service_details",
    description="Look up verified product and service offerings, specifications, features, and confirmed pricing rules directly from the business catalogue. Use this tool first whenever a customer asks about products, services, or pricing.",
    input_schema=GetProductOrServiceDetailsInput,
)
async def get_product_or_service_details(
    args: GetProductOrServiceDetailsInput,
    context: ToolExecutionContext,
) -> ProductOrServiceDetailsOutput:
    """Fetches exact products and services with strict anti-hallucination pricing guidance."""
    stmt = select(ProductService).where(
        ProductService.org_id == context.org_id,
        ProductService.is_available == True,
    )

    if args.name:
        stmt = stmt.where(ProductService.name.ilike(f"%{args.name}%"))
    if args.category:
        stmt = stmt.where(ProductService.category.ilike(f"%{args.category}%"))

    stmt = stmt.limit(5)
    res = await context.db.execute(stmt)
    products = res.scalars().all()

    items: List[ProductOrServiceItem] = []
    for p in products:
        price_str = f"{p.price:.2f}" if p.price is not None else None
        if p.pricing_type == "fixed":
            guidance = f"Confirmed price is {price_str} {p.currency}. This is a fixed and confirmed price."
        elif p.pricing_type == "starting_from":
            guidance = f"Price starts from {price_str} {p.currency}. You must clarify to the customer that this is an indicative starting price and the final cost depends on requirements."
        else:
            guidance = "Custom quotation required. You must explicitly tell the customer that quotation is required and NEVER state or guess a price."

        items.append(
            ProductOrServiceItem(
                name=p.name,
                category=p.category,
                description=p.description,
                pricing_type=p.pricing_type,
                price=price_str,
                currency=p.currency,
                features=p.features,
                benefits=p.benefits,
                specifications=p.specifications,
                pricing_guidance=guidance,
            )
        )

    return ProductOrServiceDetailsOutput(
        found=len(items) > 0,
        count=len(items),
        items=items,
    )


@tool_registry.register(
    name="get_business_policy",
    description="Retrieve company policies regarding cancellations, refunds, rescheduling, payments, warranties, or privacy.",
    input_schema=GetBusinessPolicyInput,
)
async def get_business_policy(
    args: GetBusinessPolicyInput,
    context: ToolExecutionContext,
) -> BusinessPolicyOutput:
    """Fetches verified company terms and conditions."""
    stmt = select(BusinessPolicy).where(
        BusinessPolicy.org_id == context.org_id,
        BusinessPolicy.is_active == True,
        BusinessPolicy.policy_type.ilike(f"%{args.policy_type}%"),
    )
    res = await context.db.execute(stmt)
    policies = res.scalars().all()

    items = [
        PolicyItem(
            policy_type=p.policy_type,
            title=p.title,
            content=p.content,
        )
        for p in policies
    ]

    return BusinessPolicyOutput(found=len(items) > 0, policies=items)


@tool_registry.register(
    name="get_faq_answer",
    description="Look up verified frequently asked questions (FAQs) and standardized answers.",
    input_schema=GetFAQAnswerInput,
)
async def get_faq_answer(
    args: GetFAQAnswerInput,
    context: ToolExecutionContext,
) -> FAQAnswerOutput:
    """Finds matching FAQ records for the customer's question."""
    stmt = select(FAQ).where(
        FAQ.org_id == context.org_id,
        FAQ.is_active == True,
    )
    if args.category:
        stmt = stmt.where(FAQ.category.ilike(f"%{args.category}%"))

    # Try keyword match on question or answer
    query_pattern = f"%{args.query}%"
    stmt_kw = stmt.where(FAQ.question.ilike(query_pattern) | FAQ.answer.ilike(query_pattern)).limit(3)
    res = await context.db.execute(stmt_kw)
    faqs = res.scalars().all()

    # If no exact SQL match, fallback to vector retrieval for FAQs
    if not faqs:
        results = await _knowledge_retriever.search(
            db=context.db,
            org_id=context.org_id,
            query=args.query,
            limit=2,
            document_types=["faq"],
        )
        items = [
            FAQItem(
                question=args.query,
                answer=r.content,
                category=r.document_type,
            )
            for r in results
        ]
        return FAQAnswerOutput(found=len(items) > 0, count=len(items), items=items)

    items = [
        FAQItem(
            question=f.question,
            answer=f.answer,
            category=f.category,
        )
        for f in faqs
    ]
    return FAQAnswerOutput(found=len(items) > 0, count=len(items), items=items)
