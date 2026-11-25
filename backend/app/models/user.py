"""User entity supporting multi-tenant role-based access control."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.app.models.base import GUID, Base, TenantMixin, TimestampMixin

if TYPE_CHECKING:
    from backend.app.models.organization import Organization
    from backend.app.models.employee import Employee


class User(Base, TenantMixin, TimestampMixin):
    """User account entity."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("org_id", "email", name="uq_users_org_email"),
        CheckConstraint(
            "role IN ('owner', 'admin', 'receptionist', 'employee', 'super_admin', 'sales_employee', 'ai_agent')",
            name="ck_users_valid_role",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), default="employee", nullable=False)
    phone_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    organization: Mapped["Organization"] = relationship("Organization", back_populates="users")
    employee: Mapped[Optional["Employee"]] = relationship(
        "Employee", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
