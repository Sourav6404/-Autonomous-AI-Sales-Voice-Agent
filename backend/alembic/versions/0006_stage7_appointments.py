"""Stage 7 migration: Appointment extensions for calendar management.

Revision ID: 0006_stage7_appointments
Revises: 0005_stage6_crm
Create Date: 2026-11-26 02:40:00.000000

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from backend.app.models.base import GUID


revision: str = "0006_stage7_appointments"
down_revision: Union[str, None] = "0005_stage6_crm"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("appointments") as batch_op:
        batch_op.add_column(
            sa.Column(
                "lead_id",
                GUID(),
                sa.ForeignKey("leads.id", ondelete="SET NULL"),
                nullable=True,
            )
        )
        batch_op.add_column(sa.Column("title", sa.String(255), nullable=True))
        batch_op.add_column(sa.Column("purpose", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "booking_source",
                sa.String(50),
                server_default="ai_receptionist",
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("cancellation_reason", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("timezone", sa.String(50), server_default="UTC", nullable=False)
        )
        batch_op.add_column(
            sa.Column(
                "created_by_user_id",
                GUID(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("appointments") as batch_op:
        batch_op.drop_column("created_by_user_id")
        batch_op.drop_column("timezone")
        batch_op.drop_column("cancellation_reason")
        batch_op.drop_column("booking_source")
        batch_op.drop_column("purpose")
        batch_op.drop_column("title")
        batch_op.drop_column("lead_id")
