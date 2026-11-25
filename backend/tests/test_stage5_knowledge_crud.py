"""Stage 5 tests: Business Knowledge Base CRUD, RBAC, and Tenant Isolation."""

import io
import uuid
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from backend.app.core.security import PasswordHasher, create_access_token
from backend.app.main import app
from backend.app.models.business_settings import BusinessSettings
from backend.app.models.organization import Organization
from backend.app.models.user import User


@pytest_asyncio.fixture
async def setup_tenants_and_users(db_session):
    """Creates two isolated test organizations with admin and receptionist users."""
    hashed_pwd = PasswordHasher.hash("SecurePass123!")

    # Org A
    org_a = Organization(
        id=uuid.uuid4(),
        name="Alpha Dynamics Corp",
        slug=f"alpha-{uuid.uuid4().hex[:6]}",
        is_active=True,
    )
    db_session.add(org_a)

    user_admin_a = User(
        id=uuid.uuid4(),
        org_id=org_a.id,
        email="admin@alpha.com",
        password_hash=hashed_pwd,
        full_name="Admin Alpha",
        role="admin",
        is_active=True,
    )
    user_rec_a = User(
        id=uuid.uuid4(),
        org_id=org_a.id,
        email="receptionist@alpha.com",
        password_hash=hashed_pwd,
        full_name="Receptionist Alpha",
        role="receptionist",
        is_active=True,
    )
    db_session.add_all([user_admin_a, user_rec_a])

    # Org B
    org_b = Organization(
        id=uuid.uuid4(),
        name="Beta Logistics LLC",
        slug=f"beta-{uuid.uuid4().hex[:6]}",
        is_active=True,
    )
    db_session.add(org_b)

    user_admin_b = User(
        id=uuid.uuid4(),
        org_id=org_b.id,
        email="admin@beta.com",
        password_hash=hashed_pwd,
        full_name="Admin Beta",
        role="admin",
        is_active=True,
    )
    db_session.add(user_admin_b)
    await db_session.commit()

    token_admin_a = create_access_token(subject=str(user_admin_a.id), org_id=str(org_a.id), role="admin", email=user_admin_a.email)
    token_rec_a = create_access_token(subject=str(user_rec_a.id), org_id=str(org_a.id), role="receptionist", email=user_rec_a.email)
    token_admin_b = create_access_token(subject=str(user_admin_b.id), org_id=str(org_b.id), role="admin", email=user_admin_b.email)

    return {
        "org_a": org_a,
        "org_b": org_b,
        "token_admin_a": token_admin_a,
        "token_rec_a": token_rec_a,
        "token_admin_b": token_admin_b,
    }


@pytest.mark.asyncio
async def test_company_info_crud_and_isolation(client, setup_tenants_and_users):
    """Verify company overview GET and PATCH operations with tenant isolation."""
    data = setup_tenants_and_users
    headers_a = {"Authorization": f"Bearer {data['token_admin_a']}"}
    headers_b = {"Authorization": f"Bearer {data['token_admin_b']}"}

    # 1. Admin A updates company info
    patch_payload = {
        "business_name": "Alpha Dynamics Global",
        "industry": "Artificial Intelligence",
        "website": "https://alpha.example.com",
        "contact_phone": "+1-800-555-0100",
        "contact_email": "hello@alpha.com",
        "business_address": "100 Silicon Blvd",
        "company_overview": "Leading enterprise AI voice agent solutions.",
        "business_services": "Sales AI receptionists, real-time call triage",
        "additional_info": "HIPAA compliant and SOC2 certified.",
    }
    patch_res = await client.patch("/api/v1/knowledge/company-info", headers=headers_a, json=patch_payload)
    assert patch_res.status_code == 200
    res_data = patch_res.json()
    assert res_data["business_name"] == "Alpha Dynamics Global"
    assert res_data["industry"] == "Artificial Intelligence"
    assert res_data["website"] == "https://alpha.example.com"

    # 2. Receptionist A can view company info
    headers_rec = {"Authorization": f"Bearer {data['token_rec_a']}"}
    get_res = await client.get("/api/v1/knowledge/company-info", headers=headers_rec)
    assert get_res.status_code == 200
    assert get_res.json()["business_name"] == "Alpha Dynamics Global"

    # 3. Org B has its own independent company info
    get_b_res = await client.get("/api/v1/knowledge/company-info", headers=headers_b)
    assert get_b_res.status_code == 200
    assert get_b_res.json()["business_name"] == "Beta Logistics LLC"
    assert get_b_res.json()["industry"] is None


@pytest.mark.asyncio
async def test_products_crud_and_pricing_validation(client, setup_tenants_and_users):
    """Test products & services catalogue creation, updating, deletion, and pricing types."""
    data = setup_tenants_and_users
    headers_admin = {"Authorization": f"Bearer {data['token_admin_a']}"}
    headers_rec = {"Authorization": f"Bearer {data['token_rec_a']}"}
    headers_b = {"Authorization": f"Bearer {data['token_admin_b']}"}

    # 1. Create fixed price product
    prod_payload = {
        "name": "Standard AI Voice Receptionist",
        "description": "24/7 autonomous phone triage and scheduling.",
        "category": "Voice AI",
        "price": 299.00,
        "currency": "USD",
        "pricing_type": "fixed",
        "is_available": True,
        "features": "Deepgram STT, Silero VAD, Cartesia TTS",
    }
    create_res = await client.post("/api/v1/knowledge/products", headers=headers_admin, json=prod_payload)
    assert create_res.status_code == 201
    prod_a = create_res.json()
    assert prod_a["name"] == "Standard AI Voice Receptionist"
    assert prod_a["pricing_type"] == "fixed"
    assert float(prod_a["price"]) == 299.00

    # 2. Create starting_from and quotation_required products
    prod2 = await client.post("/api/v1/knowledge/products", headers=headers_admin, json={
        "name": "Custom CRM Integration",
        "description": "Integration with legacy enterprise databases.",
        "category": "Enterprise",
        "price": 1500.00,
        "pricing_type": "starting_from",
        "is_available": True,
    })
    assert prod2.status_code == 201

    prod3 = await client.post("/api/v1/knowledge/products", headers=headers_admin, json={
        "name": "On-Premises Dedicated Voice Cluster",
        "description": "Self-hosted hardware appliance deployment.",
        "category": "Enterprise",
        "price": None,
        "pricing_type": "quotation_required",
        "is_available": True,
    })
    assert prod3.status_code == 201

    # 3. Invalid pricing type is rejected by validation
    invalid_res = await client.post("/api/v1/knowledge/products", headers=headers_admin, json={
        "name": "Invalid Item",
        "description": "Testing invalid pricing type",
        "pricing_type": "negotiable_free",
    })
    assert invalid_res.status_code == 422

    # 4. Receptionist can list products
    list_res = await client.get("/api/v1/knowledge/products", headers=headers_rec)
    assert list_res.status_code == 200
    items = list_res.json()
    assert len(items) == 3

    # 5. Org B does not see Org A's products
    list_b_res = await client.get("/api/v1/knowledge/products", headers=headers_b)
    assert list_b_res.status_code == 200
    assert len(list_b_res.json()) == 0

    # 6. Delete product
    del_res = await client.delete(f"/api/v1/knowledge/products/{prod_a['id']}", headers=headers_admin)
    assert del_res.status_code == 204

    # Verify deleted
    get_del = await client.get(f"/api/v1/knowledge/products/{prod_a['id']}", headers=headers_admin)
    assert get_del.status_code == 404


@pytest.mark.asyncio
async def test_faqs_and_policies_crud(client, setup_tenants_and_users):
    """Test FAQs and Business Policies management and RBAC."""
    data = setup_tenants_and_users
    headers_admin = {"Authorization": f"Bearer {data['token_admin_a']}"}
    headers_rec = {"Authorization": f"Bearer {data['token_rec_a']}"}

    # 1. Create FAQ
    faq_res = await client.post("/api/v1/knowledge/faqs", headers=headers_admin, json={
        "question": "What happens if a caller calls after business hours?",
        "answer": "Our AI receptionist answers immediately, takes a message, or books an appointment for the next morning.",
        "category": "Telephony",
        "is_active": True,
    })
    assert faq_res.status_code == 201
    faq = faq_res.json()
    assert "business hours" in faq["question"]

    # 2. Receptionist cannot create FAQ (RBAC check)
    rec_faq_res = await client.post("/api/v1/knowledge/faqs", headers=headers_rec, json={
        "question": "Can receptionists add FAQs?",
        "answer": "No",
    })
    assert rec_faq_res.status_code == 403

    # 3. Create Business Policy
    pol_res = await client.post("/api/v1/knowledge/policies", headers=headers_admin, json={
        "policy_type": "cancellation",
        "title": "24-Hour Appointment Cancellation Policy",
        "content": "Appointments cancelled with less than 24 hours notice are subject to a 50 USD rescheduling fee.",
        "is_active": True,
    })
    assert pol_res.status_code == 201
    policy = pol_res.json()
    assert policy["policy_type"] == "cancellation"

    # 4. List policies
    list_pol = await client.get("/api/v1/knowledge/policies", headers=headers_rec)
    assert list_pol.status_code == 200
    assert len(list_pol.json()) == 1

    # 5. FAQ Editing (PATCH)
    faq_id = faq["id"]
    patch_faq = await client.patch(
        f"/api/v1/knowledge/faqs/{faq_id}",
        headers=headers_admin,
        json={"answer": "Our AI receptionist answers immediately and transfers urgent calls to on-call staff."},
    )
    assert patch_faq.status_code == 200
    assert "transfers urgent calls" in patch_faq.json()["answer"]

    # 6. Receptionist cannot edit FAQ (RBAC check)
    rec_patch = await client.patch(
        f"/api/v1/knowledge/faqs/{faq_id}",
        headers=headers_rec,
        json={"answer": "Unauthorized update"},
    )
    assert rec_patch.status_code == 403


@pytest.mark.asyncio
async def test_document_upload_and_ingestion(client, setup_tenants_and_users):
    """Test multi-format file upload (TXT, MD) and ingestion into knowledge documents."""
    data = setup_tenants_and_users
    headers_admin = {"Authorization": f"Bearer {data['token_admin_a']}"}

    content = b"""# Customer Service Handbook 2026
Our core value is 100% transparent pricing and instant response times.
All enterprise consultations are complimentary for the first 30 minutes.
Emergency support hotline operates around the clock.
"""
    files = {"file": ("handbook.md", content, "text/markdown")}
    form_data = {"title": "Company Handbook", "document_type": "general"}

    upload_res = await client.post(
        "/api/v1/knowledge/documents/upload",
        headers=headers_admin,
        files=files,
        data=form_data,
    )
    assert upload_res.status_code == 201
    doc = upload_res.json()
    assert doc["title"] == "Company Handbook"
    assert doc["chunk_count"] >= 1
    doc_id = doc["id"]

    # List documents
    docs_list = await client.get("/api/v1/knowledge/documents", headers=headers_admin)
    assert docs_list.status_code == 200
    assert any(d["id"] == doc_id for d in docs_list.json())

    # Delete document
    del_res = await client.delete(f"/api/v1/knowledge/documents/{doc_id}", headers=headers_admin)
    assert del_res.status_code == 204


@pytest.mark.asyncio
async def test_docx_upload_retry_and_cascading_deletion(client, setup_tenants_and_users, db_session):
    """Test DOCX file upload, retry processing endpoint, and CASCADE chunk removal on delete."""
    from sqlalchemy import select
    from backend.app.models.knowledge import KnowledgeChunk
    import docx

    data = setup_tenants_and_users
    headers_admin = {"Authorization": f"Bearer {data['token_admin_a']}"}
    headers_rec = {"Authorization": f"Bearer {data['token_rec_a']}"}

    # 1. Create DOCX in memory
    doc_mem = docx.Document()
    doc_mem.add_heading("Customer Billing Terms 2026", level=1)
    doc_mem.add_paragraph("Invoices are payable within 30 days of receipt.")
    buf = io.BytesIO()
    doc_mem.save(buf)
    docx_bytes = buf.getvalue()

    files = {"file": ("billing_terms.docx", docx_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    form_data = {"title": "Billing Terms DOCX", "document_type": "policy"}

    upload_res = await client.post(
        "/api/v1/knowledge/documents/upload",
        headers=headers_admin,
        files=files,
        data=form_data,
    )
    assert upload_res.status_code == 201
    doc_obj = upload_res.json()
    doc_id = doc_obj["id"]
    assert doc_obj["chunk_count"] >= 1

    # Verify chunks exist in DB
    chunks_stmt = select(KnowledgeChunk).where(KnowledgeChunk.document_id == doc_id)
    chunks_res = await db_session.execute(chunks_stmt)
    chunks = chunks_res.scalars().all()
    assert len(chunks) >= 1

    # 2. Retry document processing endpoint
    retry_res = await client.post(
        f"/api/v1/knowledge/documents/{doc_id}/retry",
        headers=headers_admin,
    )
    assert retry_res.status_code == 200
    retried_doc = retry_res.json()
    assert retried_doc["id"] == doc_id
    assert retried_doc["chunk_count"] >= 1

    # 3. Receptionist cannot retry (RBAC check)
    rec_retry = await client.post(
        f"/api/v1/knowledge/documents/{doc_id}/retry",
        headers=headers_rec,
    )
    assert rec_retry.status_code == 403

    # 4. Delete document and verify cascading chunk removal
    del_res = await client.delete(f"/api/v1/knowledge/documents/{doc_id}", headers=headers_admin)
    assert del_res.status_code == 204

    # Verify 0 chunks remain in database for this document (CASCADE deletion)
    after_stmt = select(KnowledgeChunk).where(KnowledgeChunk.document_id == doc_id)
    after_res = await db_session.execute(after_stmt)
    assert len(after_res.scalars().all()) == 0
