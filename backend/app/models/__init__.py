"""Model package exports ensuring all models are registered on Base.metadata."""

from backend.app.models.base import Base, GUID, TenantMixin, TimestampMixin, VectorType
from backend.app.models.organization import Organization
from backend.app.models.user import User
from backend.app.models.department import Department
from backend.app.models.employee import Employee
from backend.app.models.business_settings import BusinessSettings
from backend.app.models.business_hours import BusinessHours
from backend.app.models.holiday import Holiday
from backend.app.models.special_schedule import SpecialSchedule
from backend.app.models.ai_availability import AIAvailability
from backend.app.models.customer import Customer
from backend.app.models.call import Call
from backend.app.models.conversation import Conversation
from backend.app.models.message import Message
from backend.app.models.call_summary import CallSummary
from backend.app.models.lead import Lead
from backend.app.models.appointment import Appointment
from backend.app.models.follow_up_task import FollowUpTask
from backend.app.models.knowledge import KnowledgeDocument, KnowledgeChunk
from backend.app.models.catalog import ProductService
from backend.app.models.faq import FAQ
from backend.app.models.policy import BusinessPolicy
from backend.app.models.audit_log import AuditLog

__all__ = [
    "Base",
    "GUID",
    "TenantMixin",
    "TimestampMixin",
    "VectorType",
    "Organization",
    "User",
    "Department",
    "Employee",
    "BusinessSettings",
    "BusinessHours",
    "Holiday",
    "SpecialSchedule",
    "AIAvailability",
    "Customer",
    "Call",
    "Conversation",
    "Message",
    "CallSummary",
    "Lead",
    "Appointment",
    "FollowUpTask",
    "KnowledgeDocument",
    "KnowledgeChunk",
    "ProductService",
    "FAQ",
    "BusinessPolicy",
    "AuditLog",
]
