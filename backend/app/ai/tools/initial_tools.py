"""Safe, demonstrable initial tools for sales receptionist conversations."""

import logging
from sqlalchemy import select

from backend.app.ai.tools.registry import ToolExecutionContext, tool_registry
from backend.app.ai.tools.schemas import (
    AIAvailabilityOutput,
    BusinessHoursOutput,
    BusinessInformationOutput,
    GetAIAvailabilityInput,
    GetBusinessHoursInput,
    GetBusinessInformationInput,
    HumanHandoffOutput,
    RequestHumanHandoffInput,
    WeekdayHourDetail,
)
from backend.app.models.business_hours import BusinessHours
from backend.app.models.business_settings import BusinessSettings
from backend.app.models.conversation import Conversation
from backend.app.models.organization import Organization
from backend.app.services.availability_service import AvailabilityService

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
