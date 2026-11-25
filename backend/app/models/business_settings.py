"""Business settings for receptionist and telephony defaults."""

import uuid
from typing import TYPE_CHECKING, Optional
from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.app.models.base import GUID, Base, TenantMixin, TimestampMixin

if TYPE_CHECKING:
    from backend.app.models.organization import Organization


class BusinessSettings(Base, TenantMixin, TimestampMixin):
    """Organizational business and AI receptionist operational configuration."""

    __tablename__ = "business_settings"
    __table_args__ = (
        CheckConstraint(
            "after_hours_behavior IN ('ai_voicemail', 'forward_to_number', 'ai_general_info_only', 'reject')",
            name="ck_business_settings_after_hours_behavior",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    primary_language: Mapped[str] = mapped_column(String(10), default="en", nullable=False)
    enable_multilingual: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    voice_id: Mapped[str] = mapped_column(String(100), default="sonic-english-1", nullable=False)
    after_hours_behavior: Mapped[str] = mapped_column(String(50), default="ai_voicemail", nullable=False)
    holiday_behavior: Mapped[str] = mapped_column(String(50), default="holiday_greeting", nullable=False)
    max_call_duration_seconds: Mapped[int] = mapped_column(Integer, default=900, nullable=False)
    recording_consent_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    contact_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    contact_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    business_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    business_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    business_services: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    organization: Mapped["Organization"] = relationship("Organization", back_populates="business_settings")
