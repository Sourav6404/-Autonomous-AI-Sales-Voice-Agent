"""Stage 6 CRM Dashboard statistics API."""

from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import (
    get_current_active_user,
    require_admin,
    require_receptionist,
)
from backend.app.core.database import get_db
from backend.app.models.call import Call
from backend.app.models.customer import Customer
from backend.app.models.employee import Employee
from backend.app.models.follow_up_task import FollowUpTask
from backend.app.models.inquiry import Inquiry
from backend.app.models.lead import Lead
from backend.app.models.user import User
from backend.app.schemas.crm import (
    AdminDashboardStats,
    ReceptionistDashboardStats,
    SalesDashboardStats,
)

router = APIRouter(prefix="/dashboard", tags=["CRM - Dashboard"])


def _today_range():
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, now


def _week_range():
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=7)
    return start, now


@router.get("/admin", response_model=AdminDashboardStats)
async def admin_dashboard(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Admin dashboard: org-wide stats."""
    today_start, today_end = _today_range()

    total_customers = (await db.execute(select(func.count(Customer.id)))).scalar_one()
    calls_today = (
        await db.execute(
            select(func.count(Call.id)).where(Call.started_at >= today_start)
        )
    ).scalar_one()
    total_calls = (await db.execute(select(func.count(Call.id)))).scalar_one()
    total_leads = (await db.execute(select(func.count(Lead.id)))).scalar_one()
    open_leads = (
        await db.execute(
            select(func.count(Lead.id)).where(Lead.status.in_(["new", "contacted", "qualified"]))
        )
    ).scalar_one()
    total_inquiries = (await db.execute(select(func.count(Inquiry.id)))).scalar_one()
    open_inquiries = (
        await db.execute(
            select(func.count(Inquiry.id)).where(Inquiry.status.in_(["open", "in_progress"]))
        )
    ).scalar_one()

    # Staff counts via User table
    total_employees = (
        await db.execute(select(func.count(User.id)).where(User.is_active == True))
    ).scalar_one()
    sales_employees = (
        await db.execute(
            select(func.count(User.id)).where(
                User.role.in_(["sales_employee", "employee"]), User.is_active == True
            )
        )
    ).scalar_one()
    receptionists = (
        await db.execute(
            select(func.count(User.id)).where(User.role == "receptionist", User.is_active == True)
        )
    ).scalar_one()

    return AdminDashboardStats(
        total_customers=total_customers,
        total_calls_today=calls_today,
        total_calls_all_time=total_calls,
        total_leads=total_leads,
        open_leads=open_leads,
        total_inquiries=total_inquiries,
        open_inquiries=open_inquiries,
        total_employees=total_employees,
        total_sales_employees=sales_employees,
        total_receptionists=receptionists,
    )


@router.get("/receptionist", response_model=ReceptionistDashboardStats)
async def receptionist_dashboard(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_receptionist),
):
    """Receptionist dashboard stats."""
    today_start, _ = _today_range()
    week_start, _ = _week_range()

    calls_today = (
        await db.execute(select(func.count(Call.id)).where(Call.started_at >= today_start))
    ).scalar_one()
    calls_week = (
        await db.execute(select(func.count(Call.id)).where(Call.started_at >= week_start))
    ).scalar_one()
    new_customers_today = (
        await db.execute(
            select(func.count(Customer.id)).where(Customer.created_at >= today_start)
        )
    ).scalar_one()
    open_inquiries = (
        await db.execute(
            select(func.count(Inquiry.id)).where(Inquiry.status.in_(["open", "in_progress"]))
        )
    ).scalar_one()
    new_leads_today = (
        await db.execute(
            select(func.count(Lead.id)).where(Lead.created_at >= today_start)
        )
    ).scalar_one()

    # Recent calls (last 10)
    recent_calls_result = await db.execute(
        select(Call).order_by(Call.started_at.desc()).limit(10)
    )
    recent_calls = [
        {
            "id": str(c.id),
            "caller_phone_number": c.caller_phone_number,
            "status": c.status,
            "started_at": c.started_at.isoformat() if c.started_at else None,
            "duration_seconds": c.duration_seconds,
        }
        for c in recent_calls_result.scalars().all()
    ]

    return ReceptionistDashboardStats(
        calls_today=calls_today,
        calls_this_week=calls_week,
        new_customers_today=new_customers_today,
        open_inquiries=open_inquiries,
        new_leads_today=new_leads_today,
        recent_calls=recent_calls,
    )


@router.get("/sales", response_model=SalesDashboardStats)
async def sales_dashboard(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Sales employee dashboard: stats for their own assigned leads/tasks."""
    # Find employee record
    emp_result = await db.execute(
        select(Employee).where(Employee.user_id == current_user.id)
    )
    emp = emp_result.scalar_one_or_none()
    if not emp:
        return SalesDashboardStats(
            my_leads_total=0, my_leads_new=0, my_leads_contacted=0,
            my_leads_qualified=0, my_leads_converted=0,
            my_open_tasks=0, recent_leads=[],
        )

    total = (
        await db.execute(
            select(func.count(Lead.id)).where(Lead.assigned_employee_id == emp.id)
        )
    ).scalar_one()
    new = (
        await db.execute(
            select(func.count(Lead.id)).where(
                Lead.assigned_employee_id == emp.id, Lead.status == "new"
            )
        )
    ).scalar_one()
    contacted = (
        await db.execute(
            select(func.count(Lead.id)).where(
                Lead.assigned_employee_id == emp.id, Lead.status == "contacted"
            )
        )
    ).scalar_one()
    qualified = (
        await db.execute(
            select(func.count(Lead.id)).where(
                Lead.assigned_employee_id == emp.id, Lead.status == "qualified"
            )
        )
    ).scalar_one()
    converted = (
        await db.execute(
            select(func.count(Lead.id)).where(
                Lead.assigned_employee_id == emp.id, Lead.status == "converted"
            )
        )
    ).scalar_one()
    open_tasks = (
        await db.execute(
            select(func.count(FollowUpTask.id)).where(
                FollowUpTask.assigned_employee_id == emp.id,
                FollowUpTask.is_completed == False,
            )
        )
    ).scalar_one()

    recent_leads_result = await db.execute(
        select(Lead)
        .where(Lead.assigned_employee_id == emp.id)
        .order_by(Lead.created_at.desc())
        .limit(5)
    )
    recent_leads = [
        {
            "id": str(l.id),
            "title": l.title,
            "status": l.status,
            "qualification_tier": l.qualification_tier,
            "score": l.score,
            "created_at": l.created_at.isoformat() if l.created_at else None,
        }
        for l in recent_leads_result.scalars().all()
    ]

    return SalesDashboardStats(
        my_leads_total=total,
        my_leads_new=new,
        my_leads_contacted=contacted,
        my_leads_qualified=qualified,
        my_leads_converted=converted,
        my_open_tasks=open_tasks,
        recent_leads=recent_leads,
    )
