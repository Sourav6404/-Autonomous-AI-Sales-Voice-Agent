"""Stage 6 migration: CRM, Lead Management extensions.

Revision ID: 0005_stage6_crm
Revises: 0004_stage5_knowledge_base
Create Date: 2026-11-26 02:10:00.000000

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from backend.app.models.base import GUID


revision: str = "0005_stage6_crm"
down_revision: Union[str, None] = "0004_stage5_knowledge_base"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Extend customers table with CRM fields
    with op.batch_alter_table("customers") as batch_op:
        batch_op.add_column(sa.Column("notes", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("source", sa.String(100), server_default="inbound_call", nullable=True)
        )
        batch_op.add_column(sa.Column("tags", sa.Text(), nullable=True))

    # Extend leads table with CRM fields
    with op.batch_alter_table("leads") as batch_op:
        batch_op.add_column(sa.Column("title", sa.String(255), nullable=True))
        batch_op.add_column(sa.Column("notes", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("priority", sa.String(20), server_default="medium", nullable=True)
        )
        batch_op.add_column(sa.Column("qualification_notes", sa.Text(), nullable=True))

    # Extend calls table with outcome field
    with op.batch_alter_table("calls") as batch_op:
        batch_op.add_column(sa.Column("outcome", sa.String(100), nullable=True))
        batch_op.add_column(sa.Column("notes", sa.Text(), nullable=True))

    # Create inquiries table
    op.create_table(
        "inquiries",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column(
            "org_id",
            GUID(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "customer_id",
            GUID(),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "originating_call_id",
            GUID(),
            sa.ForeignKey("calls.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "assigned_employee_id",
            GUID(),
            sa.ForeignKey("employees.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(50),
            server_default="open",
            nullable=False,
        ),
        sa.Column(
            "priority",
            sa.String(20),
            server_default="medium",
            nullable=False,
        ),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('open', 'in_progress', 'resolved', 'closed')",
            name="ck_inquiries_valid_status",
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'medium', 'high', 'urgent')",
            name="ck_inquiries_valid_priority",
        ),
    )
    op.create_index("ix_inquiries_status", "inquiries", ["status"])


def downgrade() -> None:
    op.drop_table("inquiries")

    with op.batch_alter_table("calls") as batch_op:
        batch_op.drop_column("notes")
        batch_op.drop_column("outcome")

    with op.batch_alter_table("leads") as batch_op:
        batch_op.drop_column("qualification_notes")
        batch_op.drop_column("priority")
        batch_op.drop_column("notes")
        batch_op.drop_column("title")

    with op.batch_alter_table("customers") as batch_op:
        batch_op.drop_column("tags")
        batch_op.drop_column("source")
        batch_op.drop_column("notes")
