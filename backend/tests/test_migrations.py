"""Tests for Alembic migration definitions and downgrade validity."""

import importlib
from backend.app.models.base import Base

initial_migration = importlib.import_module(
    "backend.alembic.versions.0001_initial_schema"
)


def test_migration_metadata_and_revisions():
    """Validates Alembic migration identifier and attributes."""
    assert initial_migration.revision == "0001_initial_schema"
    assert initial_migration.down_revision is None
    assert callable(initial_migration.upgrade)
    assert callable(initial_migration.downgrade)


def test_schema_tables_registered_in_metadata():
    """Validates that all key entities are registered in SQLAlchemy Base.metadata."""
    expected_tables = {
        "organizations",
        "users",
        "departments",
        "employees",
        "business_settings",
        "business_hours",
        "holidays",
        "special_schedules",
        "ai_availability",
        "customers",
        "calls",
        "conversations",
        "messages",
        "call_summaries",
        "leads",
        "appointments",
        "follow_up_tasks",
        "knowledge_documents",
        "knowledge_chunks",
        "audit_logs",
    }
    registered_tables = set(Base.metadata.tables.keys())
    assert expected_tables.issubset(registered_tables)
