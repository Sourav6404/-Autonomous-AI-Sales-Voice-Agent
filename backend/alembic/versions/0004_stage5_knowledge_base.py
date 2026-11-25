"""Stage 5 migration: Business Knowledge Base.

Revision ID: 0004_stage5_knowledge_base
Revises: 0003_stage3_conversation_engine
Create Date: 2026-11-26 01:30:00.000000

"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from backend.app.models.base import GUID


revision: str = "0004_stage5_knowledge_base"
down_revision: Union[str, None] = "0003_stage3_conversation_engine"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. products_services table
    op.create_table(
        "products_services",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("org_id", GUID(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.String(100), server_default="General", nullable=False),
        sa.Column("features", sa.Text(), nullable=True),
        sa.Column("benefits", sa.Text(), nullable=True),
        sa.Column("price", sa.Numeric(10, 2), nullable=True),
        sa.Column("currency", sa.String(10), server_default="USD", nullable=False),
        sa.Column("pricing_type", sa.String(50), server_default="fixed", nullable=False),
        sa.Column("is_available", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("specifications", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "pricing_type IN ('fixed', 'starting_from', 'quotation_required')",
            name="ck_products_services_pricing_type",
        ),
    )
    op.create_index(op.f("ix_products_services_org_id"), "products_services", ["org_id"], unique=False)
    op.create_index(op.f("ix_products_services_name"), "products_services", ["name"], unique=False)
    op.create_index(op.f("ix_products_services_category"), "products_services", ["category"], unique=False)
    op.create_index(op.f("ix_products_services_is_available"), "products_services", ["is_available"], unique=False)

    # 2. faqs table
    op.create_table(
        "faqs",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("org_id", GUID(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("category", sa.String(100), server_default="General", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(op.f("ix_faqs_org_id"), "faqs", ["org_id"], unique=False)
    op.create_index(op.f("ix_faqs_category"), "faqs", ["category"], unique=False)
    op.create_index(op.f("ix_faqs_is_active"), "faqs", ["is_active"], unique=False)

    # 3. business_policies table
    op.create_table(
        "business_policies",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("org_id", GUID(), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("policy_type", sa.String(100), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(op.f("ix_business_policies_org_id"), "business_policies", ["org_id"], unique=False)
    op.create_index(op.f("ix_business_policies_policy_type"), "business_policies", ["policy_type"], unique=False)
    op.create_index(op.f("ix_business_policies_is_active"), "business_policies", ["is_active"], unique=False)

    # 4. business_settings additions
    op.add_column("business_settings", sa.Column("website", sa.String(255), nullable=True))
    op.add_column("business_settings", sa.Column("industry", sa.String(100), nullable=True))
    op.add_column("business_settings", sa.Column("company_overview", sa.Text(), nullable=True))
    op.add_column("business_settings", sa.Column("additional_info", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("business_settings", "additional_info")
    op.drop_column("business_settings", "company_overview")
    op.drop_column("business_settings", "industry")
    op.drop_column("business_settings", "website")

    op.drop_index(op.f("ix_business_policies_is_active"), table_name="business_policies")
    op.drop_index(op.f("ix_business_policies_policy_type"), table_name="business_policies")
    op.drop_index(op.f("ix_business_policies_org_id"), table_name="business_policies")
    op.drop_table("business_policies")

    op.drop_index(op.f("ix_faqs_is_active"), table_name="faqs")
    op.drop_index(op.f("ix_faqs_category"), table_name="faqs")
    op.drop_index(op.f("ix_faqs_org_id"), table_name="faqs")
    op.drop_table("faqs")

    op.drop_index(op.f("ix_products_services_is_available"), table_name="products_services")
    op.drop_index(op.f("ix_products_services_category"), table_name="products_services")
    op.drop_index(op.f("ix_products_services_name"), table_name="products_services")
    op.drop_index(op.f("ix_products_services_org_id"), table_name="products_services")
    op.drop_table("products_services")
