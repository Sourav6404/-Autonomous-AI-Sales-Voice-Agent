"""Seed showcase data, create 6 demo accounts, and execute live testing flows."""

import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.abspath("."))

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
import httpx

from backend.app.core.config import settings
from backend.app.core.security import PasswordHasher
from backend.app.models.organization import Organization
from backend.app.models.user import User
from backend.app.models.employee import Employee
from backend.app.models.business_settings import BusinessSettings
from backend.app.models.business_hours import BusinessHours
from backend.app.models.catalog import ProductService
from backend.app.models.faq import FAQ
from backend.app.models.policy import BusinessPolicy
from backend.app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from backend.app.models.customer import Customer
from backend.app.models.lead import Lead
from backend.app.models.inquiry import Inquiry
from backend.app.models.follow_up_task import FollowUpTask
from backend.app.models.call import Call
from backend.app.models.conversation import Conversation
from backend.app.models.message import Message
from backend.app.models.appointment import Appointment
from backend.app.services.rag.embeddings import get_embedding_service


# Secure temporary local demo password
SHOWCASE_PW = "ShowcaseDemo2026!"
LIVE_PW = "LiveTestDemo2026!"


async def main():
    engine = create_async_engine(settings.async_database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    print("=" * 70)
    print("OBJECTIVE 2 & 3: CREATING DEMO USERS AND SHOWCASE DATA")
    print("=" * 70)

    async with session_factory() as db:
        # -----------------------------------------------------------------------
        # 1. SHOWCASE TENANT (Apex Nexus Systems)
        # -----------------------------------------------------------------------
        showcase_slug = "apex-nexus-showcase"
        res = await db.execute(select(Organization).where(Organization.slug == showcase_slug))
        showcase_org = res.scalar_one_or_none()
        if not showcase_org:
            showcase_org = Organization(
                id=uuid.uuid4(),
                name="Apex Nexus Robotics Inc",
                slug=showcase_slug,
                default_timezone="America/New_York",
                is_active=True,
            )
            db.add(showcase_org)
            await db.flush()
        print(f"Showcase Organization: '{showcase_org.name}' ({showcase_org.id})")

        # Business Settings for Showcase
        res = await db.execute(select(BusinessSettings).where(BusinessSettings.org_id == showcase_org.id))
        showcase_settings = res.scalar_one_or_none()
        if not showcase_settings:
            showcase_settings = BusinessSettings(
                id=uuid.uuid4(),
                org_id=showcase_org.id,
                business_description="Autonomous factory automation, warehouse robotics and enterprise inspection drones.",
                business_services="Robotics deployment, preventive fleet maintenance, predictive teleoperation software, and 24/7 technical support.",
                industry="Robotics & Industrial Automation",
                website="https://apex-robotics.example.com",
                company_overview="Apex Nexus Robotics is the industry pioneer in autonomous ground and aerial inspection systems.",
                contact_phone="+1-800-555-0199",
                contact_email="support@apex-robotics.example.com",
                business_address="500 Tech Boulevard, Innovation District, Boston, MA",
            )
            db.add(showcase_settings)
            await db.flush()

        # Business Hours (Mon-Fri 09:00 - 18:00)
        res = await db.execute(select(BusinessHours).where(BusinessHours.org_id == showcase_org.id))
        existing_hours = res.scalars().all()
        if not existing_hours:
            for day in range(1, 6):  # Mon-Fri
                bh = BusinessHours(
                    id=uuid.uuid4(),
                    org_id=showcase_org.id,
                    day_of_week=day,
                    open_time=datetime.strptime("09:00", "%H:%M").time(),
                    close_time=datetime.strptime("18:00", "%H:%M").time(),
                    is_closed=False,
                )
                db.add(bh)
            await db.flush()

        # Users: Set A (Showcase)
        showcase_users = [
            ("Admin Showcase", "admin.showcase@example.com", "admin", "VP of Operations"),
            ("Receptionist Showcase", "receptionist.showcase@example.com", "receptionist", "Chief Client Concierge"),
            ("Sales Showcase", "sales.showcase@example.com", "employee", "Senior Enterprise Account Executive"),
        ]
        created_showcase_users = {}
        for full_name, email, role, title in showcase_users:
            res = await db.execute(select(User).where(User.email == email))
            u = res.scalar_one_or_none()
            if not u:
                u = User(
                    id=uuid.uuid4(),
                    org_id=showcase_org.id,
                    email=email,
                    password_hash=PasswordHasher.hash(SHOWCASE_PW),
                    full_name=full_name,
                    role=role,
                    is_active=True,
                )
                db.add(u)
                await db.flush()
            created_showcase_users[role] = u

            # Create Employee record for Sales
            if role in ("employee", "receptionist"):
                res_emp = await db.execute(select(Employee).where(Employee.user_id == u.id))
                emp = res_emp.scalar_one_or_none()
                if not emp:
                    emp = Employee(
                        id=uuid.uuid4(),
                        org_id=showcase_org.id,
                        user_id=u.id,
                        title=title,
                        is_available_for_takeover=True,
                        is_available_for_booking=True,
                    )
                    db.add(emp)
                    await db.flush()
                created_showcase_users[f"{role}_emp"] = emp

        sales_emp = created_showcase_users["employee_emp"]

        # -----------------------------------------------------------------------
        # 2. SHOWCASE DATA SEEDING (12 Customers, 15 Leads/Inquiries, Calls, etc.)
        # -----------------------------------------------------------------------
        # Clear existing showcase demo data to keep exact counts
        await db.execute(delete(FollowUpTask).where(FollowUpTask.org_id == showcase_org.id))
        await db.execute(delete(Appointment).where(Appointment.org_id == showcase_org.id))
        await db.execute(delete(Message).where(Message.conversation_id.in_(
            select(Conversation.id).where(Conversation.org_id == showcase_org.id)
        )))
        await db.execute(delete(Conversation).where(Conversation.org_id == showcase_org.id))
        await db.execute(delete(Inquiry).where(Inquiry.org_id == showcase_org.id))
        await db.execute(delete(Lead).where(Lead.org_id == showcase_org.id))
        await db.execute(delete(Call).where(Call.org_id == showcase_org.id))
        await db.execute(delete(Customer).where(Customer.org_id == showcase_org.id))
        await db.execute(delete(ProductService).where(ProductService.org_id == showcase_org.id))
        await db.execute(delete(FAQ).where(FAQ.org_id == showcase_org.id))
        await db.execute(delete(BusinessPolicy).where(BusinessPolicy.org_id == showcase_org.id))
        await db.flush()

        # A. 5 Products / Services
        products_data = [
            ("Apex Guardian Drone X1", "Hardware", "Autonomous facility security drone with infrared lidar.", "fixed", 12500.0, "USD", "Thermal Lidar, 30-min hover, Auto-docking"),
            ("Warehouse TeleOp Fleet OS", "Software", "Cloud orchestration software for multi-rover warehouse logistics.", "starting_from", 2400.0, "USD", "Sub-centimeter tracking, API integration"),
            ("Apex Enterprise Drone Fleet Pack", "Enterprise Solution", "Turnkey deployment of 10 autonomous surveillance rovers.", "quotation_required", None, "USD", "Custom deployment, Dedicated engineer"),
            ("Annual Drone Care SLA", "Support", "Comprehensive onsite hardware warranty and preventive maintenance.", "fixed", 4800.0, "USD", "2-hour dispatch, Parts replacement"),
            ("Industrial Sensor Calibration Kit", "Accessories", "Precision calibration fixture for optical and thermal cameras.", "fixed", 750.0, "USD", "NIST traceable, Ruggedized case"),
        ]
        for name, cat, desc, p_type, price, curr, feats in products_data:
            p = ProductService(
                id=uuid.uuid4(),
                org_id=showcase_org.id,
                name=name,
                category=cat,
                description=desc,
                pricing_type=p_type,
                price=price,
                currency=curr,
                features=feats,
                is_available=True,
            )
            db.add(p)

        # B. 5 FAQs
        faqs_data = [
            ("What is the typical deployment timeline for the Guardian X1?", "Standard deployment takes 5 to 7 business days including geofence mapping and ground station configuration.", "Deployment"),
            ("Can drones operate during heavy rain or wind?", "Guardian X1 is IP67 weather-rated and operates safely in winds up to 35 knots and heavy precipitation.", "Specifications"),
            ("How does autonomous docking and recharging work?", "When battery levels reach 20%, the drone automatically returns to its heated charging nest and recharges in 45 minutes.", "Hardware"),
            ("Do you offer on-premise cloud telemetry?", "Yes, the TeleOp Fleet OS can be hosted entirely on-premise in an air-gapped sovereign Kubernetes cluster.", "Software"),
            ("What qualifications do our facility operators require?", "Our intuitive web console requires no FAA pilot license for autonomous waypoint patrol mode.", "Training"),
        ]
        for q, a, cat in faqs_data:
            f = FAQ(
                id=uuid.uuid4(),
                org_id=showcase_org.id,
                question=q,
                answer=a,
                category=cat,
                is_active=True,
            )
            db.add(f)

        # C. 3 Business Policies
        policies_data = [
            ("cancellation", "Pilot Trial Cancellation Policy", "Pilot trial agreements may be cancelled within 14 calendar days without penalty, subject to safe equipment return in original crates."),
            ("warranty", "Comprehensive Hardware Warranty", "All structural drone frames, carbon rotors, and gimbal sensors carry a 36-month full replacement warranty."),
            ("confidentiality", "Facility Data Confidentiality Policy", "All optical footage, lidar point clouds, and telemetry logs remain 100% tenant property and are encrypted end-to-end with AES-256."),
        ]
        for p_type, title, content in policies_data:
            bp = BusinessPolicy(
                id=uuid.uuid4(),
                org_id=showcase_org.id,
                policy_type=p_type,
                title=title,
                content=content,
                is_active=True,
            )
            db.add(bp)
        await db.flush()

        # D. 12 Customers
        customers_info = [
            ("Elena Vance", "elena.vance@blackmesa.example.com", "+1-555-0101", "Black Mesa Logistics"),
            ("Marcus Holloway", "marcus.h@dedsec.example.com", "+1-555-0102", "Bay Security Solutions"),
            ("Sarah Connor", "sconnor@cyberdyne.example.com", "+1-555-0103", "TechNoir Manufacturing"),
            ("Arthur Pendelton", "arthur.p@camelot.example.com", "+1-555-0104", "Avalon Supply Chain"),
            ("Dr. Gordon Freeman", "gordon.f@lambda.example.com", "+1-555-0105", "Lambda Research"),
            ("Garrus Vakarian", "garrus.v@archangel.example.com", "+1-555-0106", "Citadel Security"),
            ("Claire Redfield", "claire.r@terrasave.example.com", "+1-555-0107", "TerraSave Global"),
            ("Leon Kennedy", "leon.k@dsg.example.com", "+1-555-0108", "Division of Security Operations"),
            ("Jill Valentine", "jill.v@bsaa.example.com", "+1-555-0109", "BSAA Surveillance Unit"),
            ("Chris Redfield", "chris.r@silverdagger.example.com", "+1-555-0110", "Hound Wolf Defense"),
            ("Aloy Sobeck", "aloy.s@horizon.example.com", "+1-555-0111", "Nora Tech Renewables"),
            ("Bruce Wayne", "bwayne@wayneenterprises.example.com", "+1-555-0112", "Wayne Enterprises Logistics"),
        ]
        created_customers = []
        for name, email, phone, company in customers_info:
            parts = name.split(" ", 1)
            c = Customer(
                id=uuid.uuid4(),
                org_id=showcase_org.id,
                first_name=parts[0],
                last_name=parts[1] if len(parts) > 1 else "",
                email=email,
                phone_number=phone,
                company_name=company,
                total_calls_count=1,
                last_called_at=datetime.now(timezone.utc) - timedelta(hours=3),
            )
            db.add(c)
            created_customers.append(c)
        await db.flush()

        # E. 8 Calls & 8 Conversations with Messages
        created_calls = []
        created_convs = []
        for i in range(8):
            cust = created_customers[i]
            call = Call(
                id=uuid.uuid4(),
                org_id=showcase_org.id,
                customer_id=cust.id,
                caller_phone_number=cust.phone_number,
                callee_phone_number="+1-800-555-0199",
                status="completed" if i < 7 else "handed_off",
                outcome="appointment_booked" if i < 3 else ("lead_qualified" if i < 6 else "inquiry_answered"),
                notes=f"Inquired about Guardian X1 and facility coverage. Call rating: 5/5. Demo record #{i+1}.",
                duration_seconds=145 + i * 20,
                recording_consent_given=True,
                started_at=datetime.now(timezone.utc) - timedelta(days=i, hours=2),
                ended_at=datetime.now(timezone.utc) - timedelta(days=i, hours=1, minutes=57),
            )
            if i == 7:  # Handoff example
                call.status = "handed_off"
                call.outcome = "handed_off"
                call.notes = "Customer requested live engineer discussion regarding custom thermal integration. Transferred."

            db.add(call)
            created_calls.append(call)
            await db.flush()

            conv = Conversation(
                id=uuid.uuid4(),
                org_id=showcase_org.id,
                call_id=call.id,
                status="completed" if i < 7 else "handed_off",
                turn_count=4,
                summary=f"Customer {cust.first_name} {cust.last_name} from {cust.company_name} discussed autonomous drone specs and booked an inspection trial.",
                created_at=call.started_at,
            )
            db.add(conv)
            created_convs.append(conv)
            await db.flush()

            # Dialogue messages
            m1 = Message(
                id=uuid.uuid4(),
                conversation_id=conv.id,
                turn_number=1,
                speaker_role="caller",
                content=f"Hello, I am calling from {cust.company_name}. We need autonomous inspection drones for our warehouse.",
                created_at=call.started_at,
            )
            m2 = Message(
                id=uuid.uuid4(),
                conversation_id=conv.id,
                turn_number=2,
                speaker_role="ai_agent",
                content="Welcome to Apex Nexus Robotics! We have our Apex Guardian Drone X1 and Warehouse TeleOp Fleet OS designed specifically for warehouse coverage. Would you like to review pricing or schedule an onsite demo?",
                latency_ms=450,
                created_at=call.started_at + timedelta(seconds=2),
            )
            m3 = Message(
                id=uuid.uuid4(),
                conversation_id=conv.id,
                turn_number=3,
                speaker_role="caller",
                content="That sounds great. What is the confirmed price for the Guardian X1?",
                created_at=call.started_at + timedelta(seconds=5),
            )
            m4 = Message(
                id=uuid.uuid4(),
                conversation_id=conv.id,
                turn_number=4,
                speaker_role="ai_agent",
                content="The confirmed price for the Apex Guardian Drone X1 is $12,500.00 USD, which includes thermal lidar and auto-docking.",
                latency_ms=420,
                created_at=call.started_at + timedelta(seconds=8),
            )
            db.add_all([m1, m2, m3, m4])

        # F. 15 Leads & Inquiries
        statuses = ["new", "contacted", "qualified", "converted", "lost"]
        qual_tiers = ["hot", "warm", "cold"]
        created_leads = []
        for i in range(15):
            cust = created_customers[i % len(created_customers)]
            call_ref = created_calls[i] if i < len(created_calls) else None
            lead = Lead(
                id=uuid.uuid4(),
                org_id=showcase_org.id,
                customer_id=cust.id,
                originating_call_id=call_ref.id if call_ref else None,
                assigned_employee_id=sales_emp.id,
                status=statuses[i % len(statuses)],
                qualification_tier=qual_tiers[i % len(qual_tiers)],
                score=min(95, 60 + i * 2),
                budget_range=f"${15000 + i * 5000:,} USD",
                decision_timeline="Within 30 days" if i % 2 == 0 else "Q3 Fiscal",
                authority_confirmed=True,
                title=f"Autonomous Security Patrols for {cust.company_name}",
                notes=f"Demonstration showcase lead #{i+1}. High interest in automated drone patrols for {cust.company_name}.",
                priority="high" if i % 3 == 0 else "medium",
            )
            db.add(lead)
            created_leads.append(lead)
            await db.flush()

            # Create an inquiry for this lead
            inq = Inquiry(
                id=uuid.uuid4(),
                org_id=showcase_org.id,
                customer_id=cust.id,
                originating_call_id=call_ref.id if call_ref else None,
                subject=f"Inquiry regarding {products_data[i % len(products_data)][0]}",
                description=f"Inquired about deployment requirements and integration with existing security CCTV at {cust.company_name}.",
                status="closed" if i % 2 == 0 else "open",
                priority="high" if i % 3 == 0 else "medium",
            )
            db.add(inq)

            # Follow Up Task
            task = FollowUpTask(
                id=uuid.uuid4(),
                org_id=showcase_org.id,
                lead_id=lead.id,
                assigned_employee_id=sales_emp.id,
                title=f"Discovery consultation follow-up #{i+1}",
                description=f"Conducted discovery session with {cust.first_name} {cust.last_name}. Customer requested formal proposal and security whitepaper.",
                priority="high" if i % 3 == 0 else "medium",
                due_date=datetime.now(timezone.utc) + timedelta(days=2),
                is_completed=(i % 2 == 0),
            )
            db.add(task)

        # G. 6 Appointments
        base_time = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) + timedelta(days=1)
        for i in range(6):
            cust = created_customers[i]
            lead = created_leads[i]
            appt_start = base_time + timedelta(days=i, hours=2)
            appt_end = appt_start + timedelta(minutes=45)
            appt = Appointment(
                id=uuid.uuid4(),
                org_id=showcase_org.id,
                customer_id=cust.id,
                lead_id=lead.id,
                created_by_user_id=created_showcase_users["receptionist"].id,
                employee_id=sales_emp.id,
                title=f"Onsite Drone Patrol Demonstration - {cust.company_name}",
                purpose="Product inspection and drone flight trial",
                start_time=appt_start,
                end_time=appt_end,
                timezone="America/New_York",
                status="confirmed" if i < 4 else ("completed" if i == 4 else "cancelled"),
                booking_source="ai_receptionist",
                meeting_type="Onsite Demonstration",
            )
            db.add(appt)

        await db.commit()
        print("Showcase Tenant seeded successfully with 12 Customers, 15 Leads, 8 Calls, 8 Conversations, 6 Appointments, 5 Products, 5 FAQs, 3 Policies!")

        # -----------------------------------------------------------------------
        # 3. LIVE TESTING TENANT (FortiSales Live Testing Corp)
        # -----------------------------------------------------------------------
        live_slug = "fortisales-live-testing"
        res = await db.execute(select(Organization).where(Organization.slug == live_slug))
        live_org = res.scalar_one_or_none()
        if not live_org:
            live_org = Organization(
                id=uuid.uuid4(),
                name="FortiSales Live Testing Corp",
                slug=live_slug,
                default_timezone="America/New_York",
                is_active=True,
            )
            db.add(live_org)
            await db.flush()
        print(f"Live Organization: '{live_org.name}' ({live_org.id})")

        # Business Settings for Live
        res = await db.execute(select(BusinessSettings).where(BusinessSettings.org_id == live_org.id))
        live_settings = res.scalar_one_or_none()
        if not live_settings:
            live_settings = BusinessSettings(
                id=uuid.uuid4(),
                org_id=live_org.id,
                business_description="Enterprise Sales & Voice Automation Testing Laboratory.",
                business_services="Live test call dispatching, RAG verification, and real-time CRM updates.",
                industry="Software Testing & Sales Automation",
                website="https://live-test.fortisales.example.com",
                contact_phone="+1-888-555-0999",
                contact_email="live-test@fortisales.example.com",
            )
            db.add(live_settings)
            await db.flush()

        # Business Hours for Live
        res = await db.execute(select(BusinessHours).where(BusinessHours.org_id == live_org.id))
        if not res.scalars().all():
            for day in range(1, 6):
                db.add(BusinessHours(
                    id=uuid.uuid4(),
                    org_id=live_org.id,
                    day_of_week=day,
                    open_time=datetime.strptime("08:00", "%H:%M").time(),
                    close_time=datetime.strptime("19:00", "%H:%M").time(),
                    is_closed=False,
                ))
            await db.flush()

        # Users: Set B (Live Testing)
        live_users = [
            ("Admin Live", "admin.live@example.com", "admin", "System Administrator"),
            ("Receptionist Live", "receptionist.live@example.com", "receptionist", "Front Desk Representative"),
            ("Sales Live", "sales.live@example.com", "employee", "Account Executive"),
        ]
        created_live_users = {}
        for full_name, email, role, title in live_users:
            res = await db.execute(select(User).where(User.email == email))
            u = res.scalar_one_or_none()
            if not u:
                u = User(
                    id=uuid.uuid4(),
                    org_id=live_org.id,
                    email=email,
                    password_hash=PasswordHasher.hash(LIVE_PW),
                    full_name=full_name,
                    role=role,
                    is_active=True,
                )
                db.add(u)
                await db.flush()
            created_live_users[role] = u

            if role in ("employee", "receptionist"):
                res_emp = await db.execute(select(Employee).where(Employee.user_id == u.id))
                emp = res_emp.scalar_one_or_none()
                if not emp:
                    emp = Employee(
                        id=uuid.uuid4(),
                        org_id=live_org.id,
                        user_id=u.id,
                        title=title,
                        is_available_for_takeover=True,
                        is_available_for_booking=True,
                    )
                    db.add(emp)
                    await db.flush()
                created_live_users[f"{role}_emp"] = emp

        await db.commit()
        print("Live Testing Tenant created successfully with 3 clean testing accounts!")

    # ---------------------------------------------------------------------------
    # WRITE CREDENTIALS OUTSIDE GIT
    # ---------------------------------------------------------------------------
    cred_content = f"""# FortiSales AI - Verified Local Demo & Live Testing Credentials
Generated At: {datetime.now(timezone.utc).isoformat()}
Host: http://127.0.0.1:8000

========================================================================================
SET A — SHOWCASE ACCOUNTS (Pre-populated with rich synthetic sales/receptionist data)
Organization: Apex Nexus Robotics Inc (slug: apex-nexus-showcase)
========================================================================================
1. Admin Showcase
   - Email:       admin.showcase@example.com
   - Password:    {SHOWCASE_PW}
   - Role:        admin
   - Portal:      http://127.0.0.1:8000/admin-dashboard

2. Receptionist Showcase
   - Email:       receptionist.showcase@example.com
   - Password:    {SHOWCASE_PW}
   - Role:        receptionist
   - Portal:      http://127.0.0.1:8000/receptionist-dashboard
   - Voice Call:  http://127.0.0.1:8000/voice-console

3. Sales Showcase
   - Email:       sales.showcase@example.com
   - Password:    {SHOWCASE_PW}
   - Role:        employee (sales)
   - Portal:      http://127.0.0.1:8000/sales-dashboard

========================================================================================
SET B — LIVE TESTING ACCOUNTS (Isolated clean workspace for real live operations)
Organization: FortiSales Live Testing Corp (slug: fortisales-live-testing)
========================================================================================
4. Admin Live
   - Email:       admin.live@example.com
   - Password:    {LIVE_PW}
   - Role:        admin
   - Portal:      http://127.0.0.1:8000/admin-dashboard

5. Receptionist Live
   - Email:       receptionist.live@example.com
   - Password:    {LIVE_PW}
   - Role:        receptionist
   - Portal:      http://127.0.0.1:8000/receptionist-dashboard
   - Voice Call:  http://127.0.0.1:8000/voice-console

6. Sales Live
   - Email:       sales.live@example.com
   - Password:    {LIVE_PW}
   - Role:        employee (sales)
   - Portal:      http://127.0.0.1:8000/sales-dashboard
"""
    cred_path = "e:/pep/fortisales_demo_credentials.txt"
    with open(cred_path, "w", encoding="utf-8") as f:
        f.write(cred_content)
    print(f"\nDemo credentials written to: {cred_path}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
