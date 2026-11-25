"""Stage 2 migration: update roles check constraint, business settings fields, and AI availability temporary offline fields.

Revision ID: 0002_stage2_business_and_roles
Revises: 0001_initial_schema
Create Date: 2026-11-25 23:10:00.000000

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "0002_stage2_business_and_roles"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Update users check constraint for role
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_constraint("ck_users_valid_role", "users", type_="check")
        op.create_check_constraint(
            "ck_users_valid_role",
            "users",
            "role IN ('owner', 'admin', 'receptionist', 'employee', 'super_admin', 'sales_employee', 'ai_agent')",
        )

    # 2. Add contact and profile columns to business_settings
    op.add_column("business_settings", sa.Column("contact_phone", sa.String(length=50), nullable=True))
    op.add_column("business_settings", sa.Column("contact_email", sa.String(length=255), nullable=True))
    op.add_column("business_settings", sa.Column("business_address", sa.Text(), nullable=True))
    op.add_column("business_settings", sa.Column("business_description", sa.Text(), nullable=True))
    op.add_column("business_settings", sa.Column("business_services", sa.Text(), nullable=True))

    # 3. Add temporary offline and scheduled status columns to ai_availability
    op.add_column("ai_availability", sa.Column("temp_offline_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ai_availability", sa.Column("scheduled_status", sa.String(length=50), nullable=True))
    op.add_column("ai_availability", sa.Column("scheduled_status_change_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    # 1. Drop added columns from ai_availability
    op.drop_column("ai_availability", "scheduled_status_change_at")
    op.drop_column("ai_availability", "scheduled_status")
    op.drop_column("ai_availability", "temp_offline_until")

    # 2. Drop added columns from business_settings
    op.drop_column("business_settings", "business_services")
    op.drop_column("business_settings", "business_description")
    op.drop_column("business_settings", "business_address")
    op.drop_column("business_settings", "contact_email")
    op.drop_column("business_settings", "contact_phone")

    # 3. Restore previous users role check constraint
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_constraint("ck_users_valid_role", "users", type_="check")
        op.create_check_constraint(
            "ck_users_valid_role",
            "users",
            "role IN ('super_admin', 'admin', 'receptionist', 'sales_employee', 'ai_agent')",
        )
