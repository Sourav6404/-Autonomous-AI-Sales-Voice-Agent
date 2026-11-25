"""API v1 master router aggregating sub-routers."""

from fastapi import APIRouter
from backend.app.api.v1.ai_availability import router as ai_availability_router
from backend.app.api.v1.appointments import router as appointments_router
from backend.app.api.v1.auth import router as auth_router
from backend.app.api.v1.business_hours import router as business_hours_router
from backend.app.api.v1.business_settings import router as business_settings_router
from backend.app.api.v1.conversations import router as conversations_router
from backend.app.api.v1.crm_dashboard import router as crm_dashboard_router
from backend.app.api.v1.customers import router as customers_router
from backend.app.api.v1.employees import router as employees_router
from backend.app.api.v1.health import router as health_router
from backend.app.api.v1.holidays import router as holidays_router
from backend.app.api.v1.inquiries import router as inquiries_router
from backend.app.api.v1.knowledge import router as knowledge_router
from backend.app.api.v1.leads import router as leads_router
from backend.app.api.v1.organizations import router as organizations_router
from backend.app.api.v1.special_schedules import router as special_schedules_router
from backend.app.api.v1.voice import router as voice_router

api_v1_router = APIRouter()
api_v1_router.include_router(health_router)
api_v1_router.include_router(auth_router)
api_v1_router.include_router(organizations_router)
api_v1_router.include_router(business_settings_router)
api_v1_router.include_router(business_hours_router)
api_v1_router.include_router(holidays_router)
api_v1_router.include_router(special_schedules_router)
api_v1_router.include_router(ai_availability_router)
api_v1_router.include_router(conversations_router)
api_v1_router.include_router(voice_router)
api_v1_router.include_router(knowledge_router)
# Stage 6 CRM
api_v1_router.include_router(customers_router)
api_v1_router.include_router(leads_router)
api_v1_router.include_router(inquiries_router)
api_v1_router.include_router(employees_router)
api_v1_router.include_router(crm_dashboard_router)
# Stage 7 Appointments & Calendar
api_v1_router.include_router(appointments_router)
