"""Initial database schema migration for FortiSales AI.

Revision ID: 0001_initial_schema
Revises: None
Create Date: 2026-11-25 21:55:00.000000

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from backend.app.models.base import VectorType

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Enable required PostgreSQL extensions if dialect is postgresql
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";")
        op.execute("CREATE EXTENSION IF NOT EXISTS \"btree_gist\";")
        op.execute("CREATE EXTENSION IF NOT EXISTS \"vector\";")

    # 2. Organizations
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("default_timezone", sa.String(50), nullable=False, server_default="UTC"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"], unique=True)

    # 3. Users
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("role", sa.String(50), nullable=False, server_default="sales_employee"),
        sa.Column("phone_number", sa.String(50), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "email", name="uq_users_org_email"),
        sa.CheckConstraint("role IN ('super_admin', 'admin', 'receptionist', 'sales_employee', 'ai_agent')", name="ck_users_valid_role"),
    )
    op.create_index("ix_users_org_id", "users", ["org_id"])
    op.create_index("ix_users_email", "users", ["email"])

    # 4. Departments
    op.create_table(
        "departments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("fallback_phone", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "name", name="uq_departments_org_name"),
    )
    op.create_index("ix_departments_org_id", "departments", ["org_id"])

    # 5. Employees
    op.create_table(
        "employees",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("department_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("departments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(100), nullable=True),
        sa.Column("calendar_sync_email", sa.String(255), nullable=True),
        sa.Column("appointment_slot_duration_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("is_available_for_takeover", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_available_for_booking", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_employees_org_id", "employees", ["org_id"])
    op.create_index("ix_employees_department_id", "employees", ["department_id"])

    # 6. Business Settings
    op.create_table(
        "business_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("primary_language", sa.String(10), nullable=False, server_default="en"),
        sa.Column("enable_multilingual", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("voice_id", sa.String(100), nullable=False, server_default="sonic-english-1"),
        sa.Column("after_hours_behavior", sa.String(50), nullable=False, server_default="ai_voicemail"),
        sa.Column("holiday_behavior", sa.String(50), nullable=False, server_default="holiday_greeting"),
        sa.Column("max_call_duration_seconds", sa.Integer(), nullable=False, server_default="900"),
        sa.Column("recording_consent_required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("after_hours_behavior IN ('ai_voicemail', 'forward_to_number', 'ai_general_info_only', 'reject')", name="ck_business_settings_after_hours_behavior"),
    )

    # 7. Business Hours
    op.create_table(
        "business_hours",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("department_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("departments.id", ondelete="CASCADE"), nullable=True),
        sa.Column("day_of_week", sa.SmallInteger(), nullable=False),
        sa.Column("open_time", sa.Time(), nullable=False),
        sa.Column("close_time", sa.Time(), nullable=False),
        sa.Column("is_closed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_business_hours_day_of_week"),
        sa.CheckConstraint("open_time < close_time", name="ck_business_hours_time_order"),
    )
    op.create_index("ix_business_hours_org_id", "business_hours", ["org_id"])
    op.create_index("ix_business_hours_department_id", "business_hours", ["department_id"])

    # 8. Holidays
    op.create_table(
        "holidays",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("is_recurring_yearly", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("special_announcement", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("start_date <= end_date", name="ck_holidays_date_order"),
    )
    op.create_index("ix_holidays_org_id", "holidays", ["org_id"])

    # 9. Special Schedules
    op.create_table(
        "special_schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("department_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("departments.id", ondelete="CASCADE"), nullable=True),
        sa.Column("schedule_date", sa.Date(), nullable=False),
        sa.Column("open_time", sa.Time(), nullable=True),
        sa.Column("close_time", sa.Time(), nullable=True),
        sa.Column("is_closed_all_day", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "department_id", "schedule_date", name="uq_special_schedules_org_dept_date"),
    )
    op.create_index("ix_special_schedules_org_id", "special_schedules", ["org_id"])

    # 10. AI Availability
    op.create_table(
        "ai_availability",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("department_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("departments.id", ondelete="CASCADE"), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="online"),
        sa.Column("auto_schedule_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("emergency_closure_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("emergency_reason", sa.Text(), nullable=True),
        sa.Column("last_status_change_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("changed_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "department_id", name="uq_ai_availability_org_dept"),
        sa.CheckConstraint("status IN ('online', 'offline', 'maintenance', 'takeover_only')", name="ck_ai_availability_valid_status"),
    )
    op.create_index("ix_ai_availability_org_id", "ai_availability", ["org_id"])

    # 11. Customers
    op.create_table(
        "customers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("phone_number", sa.String(50), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("first_name", sa.String(100), nullable=True),
        sa.Column("last_name", sa.String(100), nullable=True),
        sa.Column("company_name", sa.String(150), nullable=True),
        sa.Column("total_calls_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_called_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("org_id", "phone_number", name="uq_customers_org_phone"),
    )
    op.create_index("ix_customers_org_id", "customers", ["org_id"])
    op.create_index("ix_customers_phone_number", "customers", ["phone_number"])

    # 12. Calls
    op.create_table(
        "calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("department_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("departments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("taken_over_by_employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("telephony_call_sid", sa.String(100), nullable=True, unique=True),
        sa.Column("caller_phone_number", sa.String(50), nullable=False),
        sa.Column("callee_phone_number", sa.String(50), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="initiated"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("recording_url", sa.String(1024), nullable=True),
        sa.Column("recording_consent_given", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sentiment_overall", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('initiated', 'in_progress', 'completed', 'handed_off', 'dropped', 'failed')", name="ck_calls_valid_status"),
    )
    op.create_index("ix_calls_org_id", "calls", ["org_id"])
    op.create_index("ix_calls_status", "calls", ["status"])

    # 13. Conversations
    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("call_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("calls.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("language", sa.String(10), nullable=False, server_default="en"),
        sa.Column("turn_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # 14. Messages
    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("turn_number", sa.Integer(), nullable=False),
        sa.Column("speaker_role", sa.String(30), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sentiment", sa.String(30), nullable=True),
        sa.Column("confidence_score", sa.Numeric(4, 3), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("conversation_id", "turn_number", name="uq_messages_conversation_turn"),
        sa.CheckConstraint("speaker_role IN ('caller', 'ai_agent', 'human_agent', 'system')", name="ck_messages_valid_speaker"),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])

    # 15. Call Summaries
    op.create_table(
        "call_summaries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("call_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("calls.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("primary_intent", sa.String(100), nullable=False),
        sa.Column("executive_summary", sa.Text(), nullable=False),
        sa.Column("key_points_discussed", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("customer_objections", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("action_items", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("lead_qualification_summary", sa.Text(), nullable=True),
        sa.Column("follow_up_recommended", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # 16. Leads
    op.create_table(
        "leads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("originating_call_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("calls.id", ondelete="SET NULL"), nullable=True, unique=True),
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(50), nullable=False, server_default="new"),
        sa.Column("qualification_tier", sa.String(20), nullable=False, server_default="cold"),
        sa.Column("budget_range", sa.String(100), nullable=True),
        sa.Column("decision_timeline", sa.String(100), nullable=True),
        sa.Column("authority_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("extracted_needs", sa.Text(), nullable=True),
        sa.Column("assigned_employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("score BETWEEN 0 AND 100", name="ck_leads_score_range"),
        sa.CheckConstraint("status IN ('new', 'contacted', 'qualified', 'unqualified', 'converted', 'lost')", name="ck_leads_valid_status"),
        sa.CheckConstraint("qualification_tier IN ('cold', 'warm', 'hot')", name="ck_leads_valid_tier"),
    )
    op.create_index("ix_leads_org_id", "leads", ["org_id"])
    op.create_index("ix_leads_customer_id", "leads", ["customer_id"])
    op.create_index("ix_leads_assigned_employee_id", "leads", ["assigned_employee_id"])

    # 17. Appointments
    op.create_table(
        "appointments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("originating_call_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("calls.id", ondelete="SET NULL"), nullable=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="scheduled"),
        sa.Column("meeting_type", sa.String(100), nullable=False, server_default="Sales Discovery Call"),
        sa.Column("meeting_link_or_phone", sa.String(255), nullable=True),
        sa.Column("calendar_event_id", sa.String(255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("start_time < end_time", name="ck_appointments_time_order"),
        sa.CheckConstraint("status IN ('scheduled', 'confirmed', 'completed', 'cancelled', 'no_show')", name="ck_appointments_valid_status"),
    )
    op.create_index("ix_appointments_org_id", "appointments", ["org_id"])
    op.create_index("ix_appointments_customer_id", "appointments", ["customer_id"])
    op.create_index("ix_appointments_employee_id", "appointments", ["employee_id"])
    op.create_index("ix_appointments_start_time", "appointments", ["start_time"])

    # PostgreSQL Appointment Overlap Protection using GiST exclusion constraint
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            ALTER TABLE appointments ADD CONSTRAINT no_overlapping_appointments
            EXCLUDE USING gist (
                employee_id WITH =,
                tstzrange(start_time, end_time) WITH &&
            ) WHERE (status NOT IN ('cancelled', 'no_show'));
            """
        )

    # 18. Follow-Up Tasks
    op.create_table(
        "follow_up_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=True),
        sa.Column("assigned_employee_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("priority", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_completed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("priority IN ('low', 'medium', 'high', 'urgent')", name="ck_follow_up_tasks_valid_priority"),
    )
    op.create_index("ix_follow_up_tasks_org_id", "follow_up_tasks", ["org_id"])
    op.create_index("ix_follow_up_tasks_assigned_employee_id", "follow_up_tasks", ["assigned_employee_id"])

    # 19. Knowledge Documents
    op.create_table(
        "knowledge_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("department_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("departments.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("document_type", sa.String(50), nullable=False, server_default="general"),
        sa.Column("file_path", sa.String(1024), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("document_type IN ('faq', 'product_spec', 'pricing', 'policy', 'general')", name="ck_knowledge_docs_valid_type"),
    )
    op.create_index("ix_knowledge_documents_org_id", "knowledge_documents", ["org_id"])

    # 20. Knowledge Chunks with Vector
    if bind.dialect.name == "postgresql":
        op.create_table(
            "knowledge_chunks",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False),
            sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("chunk_index", sa.Integer(), nullable=False),
            sa.Column("chunk_content", sa.Text(), nullable=False),
            sa.Column("embedding", VectorType(384), nullable=False),
            sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.execute(
            """
            CREATE INDEX idx_knowledge_chunks_embedding ON knowledge_chunks
            USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64);
            """
        )
    else:
        op.create_table(
            "knowledge_chunks",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("document_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False),
            sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("chunk_index", sa.Integer(), nullable=False),
            sa.Column("chunk_content", sa.Text(), nullable=False),
            sa.Column("embedding", sa.Text(), nullable=False),
            sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
    op.create_index("ix_knowledge_chunks_org_id", "knowledge_chunks", ["org_id"])
    op.create_index("ix_knowledge_chunks_document_id", "knowledge_chunks", ["document_id"])

    # 21. Audit Logs
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.Column("payload_diff", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_audit_logs_org_id", "audit_logs", ["org_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])


def downgrade() -> None:
    tables = [
        "audit_logs",
        "knowledge_chunks",
        "knowledge_documents",
        "follow_up_tasks",
        "appointments",
        "leads",
        "call_summaries",
        "messages",
        "conversations",
        "calls",
        "customers",
        "ai_availability",
        "special_schedules",
        "holidays",
        "business_hours",
        "business_settings",
        "employees",
        "departments",
        "users",
        "organizations",
    ]
    for table in tables:
        op.drop_table(table)
