"""Base declarative models and mixins."""

import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional
from sqlalchemy import DateTime, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column
from sqlalchemy.types import CHAR, TypeDecorator, UserDefinedType


class GUID(TypeDecorator):
    """Platform-independent GUID/UUID type.

    Uses PostgreSQL's native UUID type, otherwise uses CHAR(36), storing as stringified hex.
    """

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql":
            return value
        if not isinstance(value, uuid.UUID):
            return str(uuid.UUID(value))
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(value)


class VectorType(UserDefinedType):
    """PostgreSQL pgvector vector type."""

    def __init__(self, dim: int = 384):
        self.dim = dim

    def get_col_spec(self, **kw):
        return f"vector({self.dim})"

    def bind_processor(self, dialect):
        def process(value):
            if value is None:
                return None
            if isinstance(value, (list, tuple)):
                return f"[{','.join(str(float(x)) for x in value)}]"
            return str(value)

        return process

    def result_processor(self, dialect, coltype):
        def process(value):
            if value is None:
                return None
            if isinstance(value, str):
                cleaned = value.strip("[]")
                if not cleaned:
                    return []
                return [float(x) for x in cleaned.split(",")]
            return value

        return process


class Base(DeclarativeBase):
    """Root declarative base."""

    pass


class TimestampMixin:
    """Provides created_at and updated_at UTC timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class TenantMixin:
    """Enforces multi-tenant data isolation by associating entity with an organization."""

    @declared_attr
    def org_id(cls) -> Mapped[uuid.UUID]:
        from backend.app.core.tenant import TenantContext
        return mapped_column(
            GUID(),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            default=lambda: TenantContext.get_current_tenant_id(),
            nullable=False,
            index=True,
        )
