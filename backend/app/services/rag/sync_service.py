"""Synchronization service connecting structured business records to vector RAG chunks."""

import uuid
from typing import Optional
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.core.logging import get_logger
from backend.app.models.business_settings import BusinessSettings
from backend.app.models.catalog import ProductService
from backend.app.models.faq import FAQ
from backend.app.models.knowledge import KnowledgeDocument
from backend.app.models.policy import BusinessPolicy
from backend.app.services.rag.ingestion import DocumentIngestionService

logger = get_logger("services.rag.sync")


class KnowledgeSyncService:
    """Synchronizes structured business data (catalogue, FAQs, policies, settings) into vector RAG."""

    def __init__(self):
        self.ingestion = DocumentIngestionService()

    async def _remove_existing_document(self, db: AsyncSession, org_id: uuid.UUID, title: str):
        """Remove any previously synced knowledge document by title."""
        stmt = select(KnowledgeDocument).where(
            KnowledgeDocument.org_id == org_id,
            KnowledgeDocument.title == title,
        )
        res = await db.execute(stmt)
        existing = res.scalars().all()
        for doc in existing:
            await db.delete(doc)
        await db.flush()

    async def sync_product(self, db: AsyncSession, product: ProductService) -> Optional[KnowledgeDocument]:
        """Convert a ProductService catalogue item into a searchable knowledge document."""
        if not product.is_available:
            await self._remove_existing_document(db, product.org_id, f"Product/Service: {product.name}")
            return None

        # Build anti-hallucination structured representation
        lines = [
            f"Product or Service: {product.name}",
            f"Category: {product.category}",
            f"Description: {product.description}",
        ]
        if product.pricing_type == "fixed":
            price_val = f"{product.price:.2f}" if product.price is not None else "0.00"
            lines.append(f"Pricing: Fixed confirmed price of {price_val} {product.currency}.")
        elif product.pricing_type == "starting_from":
            price_val = f"{product.price:.2f}" if product.price is not None else "0.00"
            lines.append(f"Pricing: Starting from {price_val} {product.currency}. Final price varies based on scope or options.")
        else:
            lines.append("Pricing: Custom quotation required. There is no standard fixed price; quotation must be requested.")

        if product.features:
            lines.append(f"Key Features: {product.features}")
        if product.benefits:
            lines.append(f"Benefits: {product.benefits}")
        if product.specifications:
            lines.append(f"Technical Specifications: {product.specifications}")

        content = "\n".join(lines)
        title = f"Product/Service: {product.name}"

        await self._remove_existing_document(db, product.org_id, title)
        return await self.ingestion.ingest_raw_text(
            db=db,
            org_id=product.org_id,
            title=title,
            text_content=content,
            document_type="product_spec",
        )

    async def sync_faq(self, db: AsyncSession, faq: FAQ) -> Optional[KnowledgeDocument]:
        """Convert an FAQ into a searchable knowledge document."""
        title = f"FAQ: {faq.question[:50]}"
        if not faq.is_active:
            await self._remove_existing_document(db, faq.org_id, title)
            return None

        content = f"Category: {faq.category}\nQuestion: {faq.question}\nAnswer: {faq.answer}"
        await self._remove_existing_document(db, faq.org_id, title)
        return await self.ingestion.ingest_raw_text(
            db=db,
            org_id=faq.org_id,
            title=title,
            text_content=content,
            document_type="faq",
        )

    async def sync_policy(self, db: AsyncSession, policy: BusinessPolicy) -> Optional[KnowledgeDocument]:
        """Convert a Business Policy into a searchable knowledge document."""
        title = f"Policy: {policy.title}"
        if not policy.is_active:
            await self._remove_existing_document(db, policy.org_id, title)
            return None

        content = f"Policy Type: {policy.policy_type}\nPolicy Title: {policy.title}\nTerms and Details:\n{policy.content}"
        await self._remove_existing_document(db, policy.org_id, title)
        return await self.ingestion.ingest_raw_text(
            db=db,
            org_id=policy.org_id,
            title=title,
            text_content=content,
            document_type="policy",
        )

    async def sync_company_info(
        self,
        db: AsyncSession,
        org_id: uuid.UUID,
        org_name: str,
        settings: BusinessSettings,
    ) -> KnowledgeDocument:
        """Convert company overview and business settings into a searchable knowledge document."""
        title = "Company Overview & Business Information"
        lines = [
            f"Business Name: {org_name}",
        ]
        if settings.industry:
            lines.append(f"Industry: {settings.industry}")
        if settings.website:
            lines.append(f"Website: {settings.website}")
        if settings.contact_phone:
            lines.append(f"Phone: {settings.contact_phone}")
        if settings.contact_email:
            lines.append(f"Email: {settings.contact_email}")
        if settings.business_address:
            lines.append(f"Address: {settings.business_address}")
        if settings.business_description:
            lines.append(f"Description: {settings.business_description}")
        if settings.company_overview:
            lines.append(f"Overview: {settings.company_overview}")
        if settings.business_services:
            lines.append(f"Core Services: {settings.business_services}")
        if settings.additional_info:
            lines.append(f"Additional Information: {settings.additional_info}")

        content = "\n".join(lines)
        await self._remove_existing_document(db, org_id, title)
        return await self.ingestion.ingest_raw_text(
            db=db,
            org_id=org_id,
            title=title,
            text_content=content,
            document_type="general",
        )

    async def remove_entity_sync(self, db: AsyncSession, org_id: uuid.UUID, title: str):
        """Remove synced knowledge document on entity deletion."""
        await self._remove_existing_document(db, org_id, title)
