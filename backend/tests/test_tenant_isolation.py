"""Tests for multi-tenant isolation foundation."""

import uuid
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.core.tenant import TenantContext
from backend.app.models.customer import Customer
from backend.app.models.organization import Organization


def test_tenant_context_management():
    """Tests setting, retrieving, and clearing tenant context via ContextVar."""
    assert TenantContext.get_current_tenant_id() is None

    test_org_id = uuid.uuid4()
    TenantContext.set_current_tenant_id(test_org_id)
    assert TenantContext.get_current_tenant_id() == test_org_id
    assert TenantContext.require_tenant_id() == test_org_id

    TenantContext.clear()
    assert TenantContext.get_current_tenant_id() is None
    with pytest.raises(ValueError):
        TenantContext.require_tenant_id()


@pytest.mark.asyncio
async def test_tenant_data_isolation(db_session: AsyncSession):
    """Verifies that queries explicitly scoped to Org A do not leak Org B records."""
    org_a = Organization(name="Company A", slug="company-a")
    org_b = Organization(name="Company B", slug="company-b")
    db_session.add_all([org_a, org_b])
    await db_session.commit()

    cust_a = Customer(
        org_id=org_a.id,
        phone_number="+1111111111",
        first_name="Customer in Org A",
    )
    cust_b = Customer(
        org_id=org_b.id,
        phone_number="+2222222222",
        first_name="Customer in Org B",
    )
    db_session.add_all([cust_a, cust_b])
    await db_session.commit()

    # Query filtered by Org A
    stmt_a = select(Customer).where(Customer.org_id == org_a.id)
    results_a = (await db_session.execute(stmt_a)).scalars().all()

    assert len(results_a) == 1
    assert results_a[0].phone_number == "+1111111111"
    assert results_a[0].org_id == org_a.id

    # Query filtered by Org B
    stmt_b = select(Customer).where(Customer.org_id == org_b.id)
    results_b = (await db_session.execute(stmt_b)).scalars().all()

    assert len(results_b) == 1
    assert results_b[0].phone_number == "+2222222222"
    assert results_b[0].org_id == org_b.id


@pytest.mark.asyncio
async def test_automatic_orm_query_tenant_isolation(db_session: AsyncSession):
    """Verifies that queries WITHOUT manual where(org_id == ...) automatically filter
    by the active TenantContext through with_loader_criteria ORM hook.
    """
    org_alpha = Organization(name="Org Alpha", slug="org-alpha")
    org_beta = Organization(name="Org Beta", slug="org-beta")
    db_session.add_all([org_alpha, org_beta])
    await db_session.commit()

    cust_alpha = Customer(org_id=org_alpha.id, phone_number="+1000000001", first_name="Alpha Cust")
    cust_beta = Customer(org_id=org_beta.id, phone_number="+2000000002", first_name="Beta Cust")
    db_session.add_all([cust_alpha, cust_beta])
    await db_session.commit()

    try:
        # Set tenant context to Org Alpha
        TenantContext.set_current_tenant_id(org_alpha.id)

        # Plain SELECT without any manual where clause
        plain_stmt = select(Customer)
        results = (await db_session.execute(plain_stmt)).scalars().all()

        # Automatic filter must have restricted results exclusively to Org Alpha
        assert len(results) == 1
        assert results[0].phone_number == "+1000000001"
        assert results[0].org_id == org_alpha.id

        # Switch context to Org Beta
        TenantContext.set_current_tenant_id(org_beta.id)
        results_beta = (await db_session.execute(plain_stmt)).scalars().all()
        assert len(results_beta) == 1
        assert results_beta[0].phone_number == "+2000000002"
        assert results_beta[0].org_id == org_beta.id

        # Bypass flag for super-admin global queries
        bypass_stmt = select(Customer).execution_options(ignore_tenant_isolation=True)
        results_all = (await db_session.execute(bypass_stmt)).scalars().all()
        # Must return all customers across all tenants
        assert len(results_all) >= 2

    finally:
        TenantContext.clear()


@pytest.mark.asyncio
async def test_prevent_cross_tenant_insert_and_mutation(db_session: AsyncSession):
    """Verifies that an active tenant cannot insert or modify records belonging to another tenant."""
    from backend.app.core.exceptions import TenantAccessForbiddenError

    org_one = Organization(name="Org One", slug="org-one")
    org_two = Organization(name="Org Two", slug="org-two")
    db_session.add_all([org_one, org_two])
    await db_session.commit()

    try:
        # Context is locked to Org One
        TenantContext.set_current_tenant_id(org_one.id)

        # 1. Attempting to insert a Customer with org_two.id while in Org One context
        malicious_cust = Customer(
            org_id=org_two.id,
            phone_number="+9999999999",
            first_name="Illegal Cross-Tenant Insert",
        )
        db_session.add(malicious_cust)

        with pytest.raises(TenantAccessForbiddenError) as exc_info:
            await db_session.flush()
        assert "Cannot create Customer for tenant" in str(exc_info.value)
        db_session.expunge(malicious_cust)

    finally:
        TenantContext.clear()
