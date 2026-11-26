"""Live API verification flows testing authentication, RBAC, CRM, Appointments, and RAG."""

import asyncio
from datetime import datetime, timedelta, timezone
import httpx

BASE_URL = "http://127.0.0.1:8000"
LIVE_PW = "LiveTestDemo2026!"
SHOWCASE_PW = "ShowcaseDemo2026!"


async def run_live_tests():
    print("=" * 70)
    print("OBJECTIVE 4: LIVE API TESTING & RBAC VERIFICATION")
    print("=" * 70)

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15.0) as client:
        # 1. Admin Live Login
        res_admin = await client.post("/v1/auth/login", json={"email": "admin.live@example.com", "password": LIVE_PW})
        assert res_admin.status_code == 200, f"Admin login failed: {res_admin.text}"
        admin_token = res_admin.json()["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        print("1. Admin Live login: PASS (200 OK)")

        # 2. Receptionist Live Login
        res_rec = await client.post("/v1/auth/login", json={"email": "receptionist.live@example.com", "password": LIVE_PW})
        assert res_rec.status_code == 200, f"Receptionist login failed: {res_rec.text}"
        rec_token = res_rec.json()["access_token"]
        rec_headers = {"Authorization": f"Bearer {rec_token}"}
        print("2. Receptionist Live login: PASS (200 OK)")

        # 3. Sales Live Login
        res_sales = await client.post("/v1/auth/login", json={"email": "sales.live@example.com", "password": LIVE_PW})
        assert res_sales.status_code == 200, f"Sales login failed: {res_sales.text}"
        sales_token = res_sales.json()["access_token"]
        sales_headers = {"Authorization": f"Bearer {sales_token}"}
        print("3. Sales Live login: PASS (200 OK)")

        # 4. Dashboard Page Rendering
        for page in ["/admin-dashboard", "/receptionist-dashboard", "/sales-dashboard", "/voice-console", "/knowledge-console"]:
            res_page = await client.get(page)
            assert res_page.status_code == 200, f"Page {page} returned {res_page.status_code}"
            print(f"4. Render {page}: PASS (200 OK, {len(res_page.text)} bytes)")

        # 5. Customer Creation (via Receptionist)
        phone = f"+1-555-99{datetime.now().microsecond:04d}"
        cust_payload = {
            "first_name": "Alexander",
            "last_name": "Pierce",
            "email": "apierce@triskelion.example.com",
            "phone_number": phone,
            "company_name": "Insight Logistics Group",
        }
        res_cust = await client.post("/v1/customers", json=cust_payload, headers=rec_headers)
        assert res_cust.status_code in (200, 201), f"Customer creation failed: {res_cust.text}"
        customer = res_cust.json()
        cust_id = customer["id"]
        print(f"5. Customer Creation: PASS (Customer ID: {cust_id}, Name: {customer.get('first_name')} {customer.get('last_name')})")

        # Get Sales Rep Employee ID
        res_emp = await client.get("/v1/employees", headers=admin_headers)
        assert res_emp.status_code == 200
        employees = res_emp.json().get("items", [])
        sales_emp_id = None
        for emp in employees:
            if emp.get("role") in ("employee", "sales_employee") or "Sales" in (emp.get("title") or ""):
                sales_emp_id = emp["id"]
                break
        if not sales_emp_id and employees:
            sales_emp_id = employees[0]["id"]
        print(f"   Resolved Sales Rep Employee ID: {sales_emp_id}")

        # 6. Lead Creation (via Receptionist)
        lead_payload = {
            "customer_id": cust_id,
            "title": "Facility Security Rovers - 20 Units",
            "score": 85,
            "status": "new",
            "qualification_tier": "hot",
            "budget_range": "$50,000 - $75,000",
            "decision_timeline": "Immediate (2 Weeks)",
            "authority_confirmed": True,
            "notes": "Live test prospect inquiring about security drone integration.",
        }
        res_lead = await client.post("/v1/leads", json=lead_payload, headers=rec_headers)
        assert res_lead.status_code in (200, 201), f"Lead creation failed: {res_lead.text}"
        lead = res_lead.json()
        lead_id = lead["id"]
        print(f"6. Lead Creation: PASS (Lead ID: {lead_id}, Score: {lead['score']}, Status: {lead['status']})")

        # 7. Lead Assignment RBAC Check (Receptionist blocked 403, Admin allowed 200)
        if sales_emp_id:
            res_rec_block = await client.post(f"/v1/leads/{lead_id}/assign", json={"employee_id": sales_emp_id}, headers=rec_headers)
            assert res_rec_block.status_code == 403, f"Receptionist should be blocked from assigning leads, got {res_rec_block.status_code}"
            print("7a. RBAC Verification: PASS (Receptionist correctly blocked with 403 from assigning leads)")

            res_assign = await client.post(f"/v1/leads/{lead_id}/assign", json={"employee_id": sales_emp_id}, headers=admin_headers)
            assert res_assign.status_code == 200, f"Lead assignment by Admin failed: {res_assign.text}"
            print(f"7b. Lead Assignment by Admin: PASS (Assigned to Employee: {sales_emp_id})")

        # 8. Lead Status Update (via Sales Rep)
        res_status = await client.patch(f"/v1/leads/{lead_id}", json={"status": "qualified"}, headers=sales_headers)
        assert res_status.status_code == 200, f"Lead status update failed: {res_status.text}"
        print(f"8. Lead Status Update by Sales Rep: PASS (Status updated to: 'qualified')")

        # 9. Appointment Availability Check
        date_str = (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%d")
        res_avail = await client.get(f"/v1/appointments/availability?date={date_str}", headers=rec_headers)
        assert res_avail.status_code == 200, f"Availability check failed: {res_avail.text}"
        avail_data = res_avail.json()
        print(f"9. Appointment Availability Check for {date_str}: PASS (Retrieved {len(avail_data.get('available_slots', []))} available slot(s))")

        # 10. Appointment Booking with Confirmation
        start_dt = (datetime.now(timezone.utc) + timedelta(days=2)).replace(hour=14, minute=0, second=0, microsecond=0)
        end_dt = start_dt + timedelta(minutes=45)
        appt_payload = {
            "customer_id": cust_id,
            "employee_id": sales_emp_id,
            "lead_id": lead_id,
            "title": "Initial Sales Consultation - Live Test",
            "purpose": "Discuss facility rover deployment and live demo",
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
            "timezone": "America/New_York",
            "meeting_type": "Video Discovery Call",
        }
        res_appt = await client.post("/v1/appointments", json=appt_payload, headers=rec_headers)
        assert res_appt.status_code in (200, 201), f"Appointment booking failed: {res_appt.text}"
        appt = res_appt.json()
        print(f"10. Appointment Booking: PASS (Appt ID: {appt['id']}, Status: {appt['status']}, Time: {appt['start_time']})")

        # 11. Overlapping Double Booking Prevention (Must be rejected)
        res_double = await client.post("/v1/appointments", json=appt_payload, headers=rec_headers)
        assert res_double.status_code in (400, 409), f"Double booking should be rejected! Got: {res_double.status_code}"
        print(f"11. Double Booking Prevention: PASS (Correctly rejected duplicate slot with {res_double.status_code})")

        # 12. Conversation Creation
        conv_payload = {
            "customer_phone": phone,
            "language": "en",
        }
        res_conv = await client.post("/v1/conversations", json=conv_payload, headers=rec_headers)
        assert res_conv.status_code in (200, 201), f"Conversation creation failed: {res_conv.text}"
        conv = res_conv.json()
        conv_id = conv["id"]
        print(f"12. Conversation Creation: PASS (Conversation ID: {conv_id}, Status: {conv['status']})")

        # 13. RAG Knowledge Retrieval
        rag_query_payload = {
            "query": "What are your deployment timelines and services?",
            "limit": 3,
        }
        res_rag = await client.post("/v1/knowledge/query", json=rag_query_payload, headers=admin_headers)
        assert res_rag.status_code == 200, f"RAG query failed: {res_rag.text}"
        rag_res = res_rag.json()
        print(f"13. RAG Knowledge Retrieval: PASS (Query processed, retrieved {len(rag_res.get('results', []))} result(s))")

        # 14. Human Handoff Escalation
        handoff_payload = {
            "reason": "Customer requested urgent custom hardware consultation.",
            "urgency": "high",
            "customer_callback_phone": phone,
        }
        res_handoff = await client.post(f"/v1/conversations/{conv_id}/handoff", json=handoff_payload, headers=rec_headers)
        assert res_handoff.status_code in (200, 201), f"Handoff failed: {res_handoff.text}"
        handoff_res = res_handoff.json()
        print(f"14. Human Handoff Escalation: PASS (Status: {handoff_res['status']}, Reason: {handoff_payload['reason']})")

        # 15. Showcase Dashboard Stats Verification
        res_admin_showcase = await client.post("/v1/auth/login", json={"email": "admin.showcase@example.com", "password": SHOWCASE_PW})
        assert res_admin_showcase.status_code == 200
        showcase_admin_token = res_admin_showcase.json()["access_token"]
        showcase_headers = {"Authorization": f"Bearer {showcase_admin_token}"}

        res_stats = await client.get("/v1/crm/dashboard", headers=showcase_headers)
        assert res_stats.status_code == 200, f"Stats failed: {res_stats.text}"
        stats = res_stats.json()
        print("\n15. Showcase Dashboard Analytics:")
        print(f"    - Total Customers: {stats.get('total_customers')}")
        print(f"    - Total Leads: {stats.get('total_leads')}")
        print(f"    - Open Inquiries: {stats.get('open_inquiries')}")
        print(f"    - Completed Calls: {stats.get('total_calls')}")
        print(f"    - Confirmed Appointments: {stats.get('total_appointments')}")

    print("\n" + "=" * 70)
    print("ALL 15 LIVE TESTING & VERIFICATION FLOWS PASSED!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_live_tests())
