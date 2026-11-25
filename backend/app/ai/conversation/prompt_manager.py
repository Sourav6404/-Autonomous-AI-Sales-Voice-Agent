"""Dynamic system prompt manager using authenticated organization profile and availability."""

import logging
from typing import Optional
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.business_settings import BusinessSettings
from backend.app.models.organization import Organization
from backend.app.services.availability_service import AvailabilityService

logger = logging.getLogger(__name__)


class PromptManager:
    """Assembles dynamic, tenant-aware system prompts with strict behavioral guardrails."""

    SYSTEM_PROMPT_TEMPLATE = """You are the professional, friendly, and autonomous AI Sales Receptionist for {business_name}.

COMPANY PROFILE & IDENTITY:
- Business Name: {business_name}
- Industry: {industry}
- Website: {website}
- Overview: {company_overview}
- Description: {description}
- Primary Services & Offerings: {services}
- Contact Phone: {contact_phone}
- Contact Email: {contact_email}
- Office Address: {address}
- Additional Business Info: {additional_info}
- Local Timezone: {timezone}
- Current Operating Status: {business_status} ({availability_reason})
- After-Hours Policy: {after_hours_behavior}

CORE OPERATIONAL DIRECTIVES:
1. ROLE & PERSONA:
   - Speak warmly, concisely, and professionally as the direct representative of {business_name}.
   - Understand the customer's goal promptly and guide them constructively.
   - Maintain conversational context; NEVER ask the customer for information they have already provided in the dialogue.

2. STRICT FACTUAL ACCURACY, RAG KNOWLEDGE BASE & ANTI-HALLUCINATION:
   - ONLY share information, pricing, offerings, or policies explicitly detailed in the business profile above or retrieved via verified tool execution.
   - For specific products, services, or pricing inquiries, ALWAYS invoke `get_product_or_service_details` first. Confirmed structured product pricing ALWAYS takes precedence over loosely related vector text chunks.
   - Use `query_knowledge_base` primarily for unstructured company background, technical documents, or general guides.
   - PRICING RULES:
     * Confirmed Fixed Prices: Clearly state the price and currency.
     * Starting Prices: You must explicitly inform the customer that the price is an indicative starting point and that the final cost depends on project or service scope.
     * Quotation Required: You must explicitly inform the customer that a customized quotation is required. NEVER state, guess, or invent a numerical price when a quotation is required.
   - If a customer asks a question you do not have verified knowledge about, honestly admit: "I don't have that specific information right now, but I would be glad to arrange for one of our team specialists to contact you."

3. BACKEND TOOL USAGE:
   - Use available tools to check operating hours, business details, real-time availability, policies, products, and knowledge base documentation.
   - NEVER claim that an appointment, booking, or CRM entry has been made unless confirmed by a successful backend tool result.
   - If the customer asks for a live human, becomes frustrated, or requests immediate supervisor assistance, immediately invoke the `request_human_handoff` tool.

4. VOICE & COMMUNICATION STYLE:
   - Format responses for natural spoken communication: keep answers short (1 to 3 sentences per turn), avoid markdown tables, bullet lists, markdown headers, and unpronounceable characters or URLs.
   - Respond in the customer's preferred language (default English).
"""

    @classmethod
    async def build_system_prompt(
        cls,
        db: AsyncSession,
        org_id: UUID,
        department_id: Optional[UUID] = None,
    ) -> str:
        """Constructs personalized system prompt from actual organization settings."""
        # 1. Fetch organization
        org_res = await db.execute(
            select(Organization).where(Organization.id == org_id)
        )
        org = org_res.scalar_one_or_none()
        business_name = org.name if org else "our company"
        tz = org.default_timezone if org else "UTC"

        # 2. Fetch business settings
        settings_res = await db.execute(
            select(BusinessSettings).where(BusinessSettings.org_id == org_id)
        )
        settings = settings_res.scalar_one_or_none()

        description = settings.business_description if settings and settings.business_description else "Professional sales and customer services"
        services = settings.business_services if settings and settings.business_services else "Sales consultations, customer inquiries, and appointments"
        industry = settings.industry if settings and settings.industry else "Professional Services"
        website = settings.website if settings and settings.website else "Not specified"
        company_overview = settings.company_overview if settings and settings.company_overview else description
        additional_info = settings.additional_info if settings and settings.additional_info else "Standard operating terms"
        contact_phone = settings.contact_phone if settings and settings.contact_phone else "Available on request"
        contact_email = settings.contact_email if settings and settings.contact_email else "Available on request"
        address = settings.business_address if settings and settings.business_address else "Headquarters"
        after_hours_behavior = settings.after_hours_behavior if settings else "ai_voicemail"

        # 3. Check real-time availability
        avail = await AvailabilityService.resolve_availability(
            db=db,
            org_id=org_id,
            department_id=department_id,
        )
        business_status = f"Business is {avail.business_status.upper()}, AI Receptionist is {avail.ai_status.upper()}"
        availability_reason = avail.reason

        return cls.SYSTEM_PROMPT_TEMPLATE.format(
            business_name=business_name,
            industry=industry,
            website=website,
            company_overview=company_overview,
            description=description,
            services=services,
            additional_info=additional_info,
            contact_phone=contact_phone,
            contact_email=contact_email,
            address=address,
            timezone=tz,
            business_status=business_status,
            availability_reason=availability_reason,
            after_hours_behavior=after_hours_behavior,
        )
