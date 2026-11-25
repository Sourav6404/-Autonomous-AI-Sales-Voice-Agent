"""Tests for AI Tool Registry, parameter validation, and secure execution."""

from datetime import time
import uuid
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.ai.tools.initial_tools import tool_registry
from backend.app.ai.tools.registry import ToolExecutionContext
from backend.app.models.business_hours import BusinessHours
from backend.app.models.business_settings import BusinessSettings
from backend.app.models.conversation import Conversation
from backend.app.models.organization import Organization


@pytest.mark.asyncio
async def test_tool_registry_definitions():
    """Verifies that initial tools are registered and generate valid JSON schemas."""
    tools = tool_registry.get_tool_definitions()
    names = [t.name for t in tools]

    assert "get_business_information" in names
    assert "get_business_hours" in names
    assert "get_ai_availability" in names
    assert "request_human_handoff" in names

    # Verify JSON schema structure
    info_tool = next(t for t in tools if t.name == "get_business_information")
    assert "type" in info_tool.parameters
    assert info_tool.parameters["type"] == "object"


@pytest.mark.asyncio
async def test_get_business_information_tool(db_session: AsyncSession):
    """Tests executing get_business_information tool against tenant data."""
    org = Organization(name="Omni Enterprise", slug=f"omni-{uuid.uuid4().hex[:6]}", default_timezone="America/New_York")
    db_session.add(org)
    await db_session.flush()

    settings = BusinessSettings(
        org_id=org.id,
        business_description="Enterprise cloud security services",
        business_services="Cloud firewalls, Endpoint detection, AI voice reception",
        contact_phone="+1-800-555-9999",
        contact_email="contact@omni.com",
        business_address="500 Cyber Way, New York NY",
    )
    db_session.add(settings)
    await db_session.commit()

    context = ToolExecutionContext(
        org_id=org.id,
        conversation_id=uuid.uuid4(),
        db=db_session,
    )

    result = await tool_registry.execute_tool(
        name="get_business_information",
        arguments={},
        context=context,
    )

    assert result["name"] == "Omni Enterprise"
    assert result["description"] == "Enterprise cloud security services"
    assert result["contact_phone"] == "+1-800-555-9999"
    assert result["timezone"] == "America/New_York"


@pytest.mark.asyncio
async def test_get_business_hours_tool(db_session: AsyncSession):
    """Tests executing get_business_hours tool."""
    org = Organization(name="Hours Corp", slug=f"hours-{uuid.uuid4().hex[:6]}")
    db_session.add(org)
    await db_session.flush()

    # Add Monday hours
    hours = BusinessHours(
        org_id=org.id,
        day_of_week=1,
        open_time=time(8, 30),
        close_time=time(17, 30),
        is_closed=False,
    )
    db_session.add(hours)
    await db_session.commit()

    context = ToolExecutionContext(
        org_id=org.id,
        conversation_id=uuid.uuid4(),
        db=db_session,
    )

    result = await tool_registry.execute_tool(
        name="get_business_hours",
        arguments={"day_of_week": 1},
        context=context,
    )

    assert "schedules" in result
    assert len(result["schedules"]) == 1
    assert result["schedules"][0]["day"] == "Monday"
    assert result["schedules"][0]["open_time"] == "08:30:00"


@pytest.mark.asyncio
async def test_tool_execution_argument_validation():
    """Tests that passing invalid arguments to a tool returns structured validation errors."""
    context = ToolExecutionContext(
        org_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        db=None,  # type: ignore
    )

    # day_of_week must be between 0 and 6, 99 is invalid
    result = await tool_registry.execute_tool(
        name="get_business_hours",
        arguments={"day_of_week": 99},
        context=context,
    )

    assert "error" in result
    assert "Invalid arguments" in result["error"]


@pytest.mark.asyncio
async def test_tool_execution_unrecognized_tool():
    """Verifies that unknown tools are rejected safely."""
    context = ToolExecutionContext(
        org_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        db=None,  # type: ignore
    )
    result = await tool_registry.execute_tool(
        name="drop_database",
        arguments={},
        context=context,
    )
    assert "error" in result
    assert "not recognized" in result["error"]
