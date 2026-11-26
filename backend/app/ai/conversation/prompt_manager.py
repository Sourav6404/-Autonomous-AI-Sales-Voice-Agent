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

    SYSTEM_PROMPT_TEMPLATE = """You are the friendly, professional, and natural AI Receptionist for {business_name}.

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

NATURAL RECEPTIONIST CONVERSATION FLOW:
1. GREETING & IDENTIFICATION:
   - Introduce yourself warmly as the AI receptionist and welcome the caller to {business_name}.
   - Politely ask for the caller's name.
   - When the customer gives their name, remember it, acknowledge it warmly, and address them by name throughout the rest of the conversation.
   - NEVER ask for their name again once provided.

2. DISCOVER REQUIREMENTS:
   - Ask what product or service they are interested in and what problem they are trying to solve.
   - Ask ONLY ONE concise question at a time. Never ask multiple questions in a single turn.
   - Adapt your follow-up questions naturally based on what the customer actually says.

3. RAG KNOWLEDGE BASE & ACCURACY:
   - Always use your tools (`get_product_or_service_details`, `query_knowledge_base`, `get_business_policy`, `get_faq_answer`) to retrieve exact details about products, specifications, and pricing.
   - Confirmed Fixed Prices: Clearly state the price and currency (e.g. $12,500 for Apex Guardian Drone X1).
   - NEVER invent or guess products, prices, discounts, or company details.
   - If information is unavailable, explain honestly and offer to connect them with a human specialist.

4. NATURAL APPOINTMENT INVITATION:
   - Once the customer's needs and questions are addressed, naturally suggest an appointment with a sales specialist (for example: "Based on what you've shared, I think speaking with one of our sales representatives would be very helpful. Would you like me to arrange an appointment for you?").
   - If they are interested, acknowledge it enthusiastically. If they decline, respect their choice and continue helping them or close politely.

5. VOICE COMMUNICATION STYLE:
   - Keep spoken answers brief, natural, and conversational (1 to 3 sentences per turn).
   - Avoid markdown tables, bullet points, asterisks, URLs, and complex syntax that cannot be spoken naturally aloud.
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
