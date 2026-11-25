"""Stage 3 migration: Add tenant org_id, status, and summary to conversations.

Revision ID: 0003_stage3_conversation_engine
Revises: 0002_stage2_business_and_roles
Create Date: 2026-11-25 23:45:00.000000

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from backend.app.models.base import GUID


revision: str = "0003_stage3_conversation_engine"
down_revision: Union[str, None] = "0002_stage2_business_and_roles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add org_id to conversations table
    op.add_column("conversations", sa.Column("org_id", GUID(), nullable=True))
    op.create_index(op.f("ix_conversations_org_id"), "conversations", ["org_id"], unique=False)
    op.create_foreign_key(
        "fk_conversations_org_id_organizations",
        "conversations",
        "organizations",
        ["org_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Backfill org_id from parent calls if any records exist
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            UPDATE conversations c
            SET org_id = calls.org_id
            FROM calls
            WHERE c.call_id = calls.id AND c.org_id IS NULL;
            """
        )

    # 2. Add status and summary columns
    op.add_column("conversations", sa.Column("status", sa.String(length=50), server_default="active", nullable=False))
    op.create_index(op.f("ix_conversations_status"), "conversations", ["status"], unique=False)
    op.add_column("conversations", sa.Column("summary", sa.Text(), nullable=True))

    # 3. Add check constraint for status
    if bind.dialect.name == "postgresql":
        op.create_check_constraint(
            "ck_conversations_valid_status",
            "conversations",
            "status IN ('active', 'completed', 'handed_off', 'abandoned')",
        )

    # Alter call_id to nullable for text-only conversations
    op.alter_column("conversations", "call_id", nullable=True)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_constraint("ck_conversations_valid_status", "conversations", type_="check")

    op.alter_column("conversations", "call_id", nullable=False)
    op.drop_column("conversations", "summary")
    op.drop_index(op.f("ix_conversations_status"), table_name="conversations")
    op.drop_column("conversations", "status")

    op.drop_constraint("fk_conversations_org_id_organizations", "conversations", type_="foreignkey")
    op.drop_index(op.f("ix_conversations_org_id"), table_name="conversations")
    op.drop_column("conversations", "org_id")
