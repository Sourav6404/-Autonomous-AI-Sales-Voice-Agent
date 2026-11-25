"""Tests for model creation, constraints, and relationships."""

import uuid
from datetime import datetime, time, timezone
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.models.appointment import Appointment
from backend.app.models.business_hours import BusinessHours
from backend.app.models.business_settings import BusinessSettings
from backend.app.models.call import Call
from backend.app.models.call_summary import CallSummary
from backend.app.models.conversation import Conversation
from backend.app.models.customer import Customer
from backend.app.models.department import Department
from backend.app.models.employee import Employee
from backend.app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from backend.app.models.lead import Lead
from backend.app.models.message import Message
from backend.app.models.organization import Organization
from backend.app.models.user import User


@pytest.mark.asyncio
async def test_create_organization_and_user(db_session: AsyncSession):
    """Tests creating an Organization and associated User."""
    org = Organization(
        name="Acme Technologies",
        slug="acme-tech",
        default_timezone="America/New_York",
    )
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)

    assert isinstance(org.id, uuid.UUID)
    assert org.created_at is not None

    user = User(
        org_id=org.id,
        email="admin@acme.com",
        password_hash="hashed_pw_test",
        full_name="Alice Admin",
        role="admin",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    assert isinstance(user.id, uuid.UUID)
    assert user.org_id == org.id
    assert user.role == "admin"


@pytest.mark.asyncio
async def test_call_conversation_and_messages(db_session: AsyncSession):
    """Tests cascading relationships across Call, Conversation, and Message."""
    org = Organization(name="Sales Corp", slug="sales-corp")
    db_session.add(org)
    await db_session.commit()

    customer = Customer(
        org_id=org.id,
        phone_number="+15551234567",
        first_name="Bob",
        last_name="Customer",
    )
    db_session.add(customer)
    await db_session.commit()

    call = Call(
        org_id=org.id,
        customer_id=customer.id,
        caller_phone_number="+15551234567",
        callee_phone_number="+18005550199",
        status="in_progress",
    )
    db_session.add(call)
    await db_session.commit()

    conv = Conversation(call_id=call.id, language="en")
    db_session.add(conv)
    await db_session.commit()

    msg1 = Message(
        conversation_id=conv.id,
        turn_number=1,
        speaker_role="ai_agent",
        content="Hello, thank you for calling!",
    )
    msg2 = Message(
        conversation_id=conv.id,
        turn_number=2,
        speaker_role="caller",
        content="I need product pricing.",
    )
    db_session.add_all([msg1, msg2])
    await db_session.commit()

    # Query back
    result = await db_session.execute(
        select(Conversation).where(Conversation.id == conv.id)
    )
    queried_conv = result.scalar_one()
    assert queried_conv.call_id == call.id


@pytest.mark.asyncio
async def test_knowledge_document_and_chunks(db_session: AsyncSession):
    """Tests knowledge base document and vector chunks."""
    org = Organization(name="Doc Corp", slug="doc-corp")
    db_session.add(org)
    await db_session.commit()

    doc = KnowledgeDocument(
        org_id=org.id,
        title="Enterprise Pricing Guide",
        document_type="pricing",
        content_hash="abc123hash",
        chunk_count=1,
    )
    db_session.add(doc)
    await db_session.commit()

    chunk = KnowledgeChunk(
        document_id=doc.id,
        org_id=org.id,
        chunk_index=0,
        chunk_content="Enterprise plans start at $49/user/month.",
        embedding=[0.05] * 384,
        token_count=12,
    )
    db_session.add(chunk)
    await db_session.commit()

    assert chunk.document_id == doc.id
    assert chunk.org_id == org.id
