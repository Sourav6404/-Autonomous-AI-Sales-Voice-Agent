"""Product and service catalogue model."""

import uuid
from decimal import Decimal
from typing import Optional
from sqlalchemy import Boolean, CheckConstraint, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from backend.app.models.base import GUID, Base, TenantMixin, TimestampMixin


class ProductService(Base, TenantMixin, TimestampMixin):
    """Product or service entry in business knowledge catalogue."""

    __tablename__ = "products_services"
    __table_args__ = (
        CheckConstraint(
            "pricing_type IN ('fixed', 'starting_from', 'quotation_required')",
            name="ck_products_services_pricing_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(100), default="General", index=True, nullable=False)
    features: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    benefits: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="USD", nullable=False)
    pricing_type: Mapped[str] = mapped_column(
        String(50), default="fixed", nullable=False
    )
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, index=True, nullable=False)
    specifications: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
