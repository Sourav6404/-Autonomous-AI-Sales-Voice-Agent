"""Holiday and corporate closure schedule."""

import uuid
from datetime import date
from typing import TYPE_CHECKING, Optional
from sqlalchemy import Boolean, CheckConstraint, Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.app.models.base import GUID, Base, TenantMixin, TimestampMixin

if TYPE_CHECKING:
    from backend.app.models.organization import Organization


class Holiday(Base, TenantMixin, TimestampMixin):
    """Public and corporate holidays."""

    __tablename__ = "holidays"
    __table_args__ = (
        CheckConstraint("start_date <= end_date", name="ck_holidays_date_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_recurring_yearly: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    special_announcement: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    organization: Mapped["Organization"] = relationship("Organization", back_populates="holidays")
