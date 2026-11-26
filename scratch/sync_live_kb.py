import asyncio
import os
import sys
import uuid
sys.path.insert(0, os.path.abspath("."))
from sqlalchemy import select
from backend.app.core.database import AsyncSessionLocal
from backend.app.models.organization import Organization
from backend.app.models.catalog import ProductService
from backend.app.models.business_settings import BusinessSettings
from backend.app.models.faq import FAQ
from backend.app.models.policy import BusinessPolicy

async def sync():
    async with AsyncSessionLocal() as s:
        res_showcase = await s.execute(select(Organization).where(Organization.slug == "apex-nexus-showcase"))
        showcase_org = res_showcase.scalar_one_or_none()

        res_live = await s.execute(select(Organization).where(Organization.slug == "fortisales-live-testing"))
        live_org = res_live.scalar_one_or_none()

        if not showcase_org or not live_org:
            print("Orgs not found")
            return

        # 1. Sync BusinessSettings
        s_settings = (await s.execute(select(BusinessSettings).where(BusinessSettings.org_id == showcase_org.id))).scalar_one_or_none()
        l_settings = (await s.execute(select(BusinessSettings).where(BusinessSettings.org_id == live_org.id))).scalar_one_or_none()
        if s_settings and not l_settings:
            live_settings = BusinessSettings(
                id=uuid.uuid4(),
                org_id=live_org.id,
                business_description=s_settings.business_description,
                business_services=s_settings.business_services,
                industry=s_settings.industry,
                company_overview=s_settings.company_overview,
                website="https://fortisales.ai",
                contact_phone="+1 800 555 0199",
                contact_email="support@fortisales.ai",
                business_address="100 Innovation Way, Suite 400, Austin, TX",
            )
            s.add(live_settings)
            print("Added business settings to live org.")

        # 2. Sync Products
        s_products = (await s.execute(select(ProductService).where(ProductService.org_id == showcase_org.id))).scalars().all()
        l_products = (await s.execute(select(ProductService).where(ProductService.org_id == live_org.id))).scalars().all()
        if not l_products and s_products:
            for p in s_products:
                new_p = ProductService(
                    id=uuid.uuid4(),
                    org_id=live_org.id,
                    name=p.name,
                    category=p.category,
                    pricing_type=p.pricing_type,
                    price=p.price,
                    currency=p.currency,
                    description=p.description,
                    features=p.features,
                )
                s.add(new_p)
            print(f"Copied {len(s_products)} products to live org.")

        # 3. Sync FAQs
        s_faqs = (await s.execute(select(FAQ).where(FAQ.org_id == showcase_org.id))).scalars().all()
        l_faqs = (await s.execute(select(FAQ).where(FAQ.org_id == live_org.id))).scalars().all()
        if not l_faqs and s_faqs:
            for faq in s_faqs:
                new_faq = FAQ(
                    id=uuid.uuid4(),
                    org_id=live_org.id,
                    question=faq.question,
                    answer=faq.answer,
                    is_active=True,
                )
                s.add(new_faq)
            print(f"Copied {len(s_faqs)} FAQs to live org.")

        await s.commit()
        print("Knowledge base sync complete!")

asyncio.run(sync())
