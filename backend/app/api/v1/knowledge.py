"""Business Knowledge Base and RAG API Router.

Provides CRUD endpoints for:
- Company Information
- Products & Services catalogue (with confirmed vs starting price anti-hallucination)
- Frequently Asked Questions (FAQs)
- Business Policies (cancellations, refunds, warranties, privacy)
- Document ingestion (PDF, TXT, MD) and vector indexing
- Semantic RAG retrieval queries
"""

import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.api.deps import get_current_active_user, require_admin
from backend.app.core.database import get_db
from backend.app.core.logging import get_logger
from backend.app.core.tenant import TenantContext
from backend.app.models.business_settings import BusinessSettings
from backend.app.models.catalog import ProductService
from backend.app.models.faq import FAQ
from backend.app.models.knowledge import KnowledgeDocument
from backend.app.models.organization import Organization
from backend.app.models.policy import BusinessPolicy
from backend.app.models.user import User
from backend.app.schemas.knowledge import (
    BusinessPolicyCreateRequest,
    BusinessPolicyResponse,
    BusinessPolicyUpdateRequest,
    CompanyInfoResponse,
    CompanyInfoUpdateRequest,
    DocumentResponse,
    FAQCreateRequest,
    FAQResponse,
    FAQUpdateRequest,
    KnowledgeQueryRequest,
    KnowledgeQueryResponse,
    KnowledgeSearchResultItem,
    ProductServiceCreateRequest,
    ProductServiceResponse,
    ProductServiceUpdateRequest,
)
from backend.app.services.rag.ingestion import DocumentIngestionService
from backend.app.services.rag.retriever import KnowledgeRetriever
from backend.app.services.rag.sync_service import KnowledgeSyncService

logger = get_logger("api.v1.knowledge")

router = APIRouter(prefix="/knowledge", tags=["Knowledge Base & RAG"])

ingestion_service = DocumentIngestionService()
sync_service = KnowledgeSyncService()
retriever_service = KnowledgeRetriever()


# ===========================================================================
# 1. Company Information
# ===========================================================================
@router.get("/company-info", response_model=CompanyInfoResponse)
async def get_company_info(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> CompanyInfoResponse:
    """Get the current organization's profile and company knowledge overview."""
    org_id = TenantContext.get_current_tenant_id()
    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    settings_stmt = select(BusinessSettings).where(BusinessSettings.org_id == org_id)
    settings_res = await db.execute(settings_stmt)
    b_settings = settings_res.scalar_one_or_none()

    if not b_settings:
        b_settings = BusinessSettings(org_id=org_id)
        db.add(b_settings)
        await db.commit()
        await db.refresh(b_settings)

    return CompanyInfoResponse(
        business_name=org.name,
        industry=b_settings.industry,
        website=b_settings.website,
        contact_phone=b_settings.contact_phone,
        contact_email=b_settings.contact_email,
        business_address=b_settings.business_address,
        company_overview=b_settings.company_overview,
        business_description=b_settings.business_description,
        business_services=b_settings.business_services,
        additional_info=b_settings.additional_info,
        updated_at=b_settings.updated_at,
    )


@router.patch("/company-info", response_model=CompanyInfoResponse)
async def update_company_info(
    payload: CompanyInfoUpdateRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> CompanyInfoResponse:
    """Update organization profile, overview, contact details, and sync to RAG."""
    org_id = TenantContext.get_current_tenant_id()
    org = await db.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    if payload.business_name is not None and payload.business_name.strip():
        org.name = payload.business_name.strip()

    settings_stmt = select(BusinessSettings).where(BusinessSettings.org_id == org_id)
    settings_res = await db.execute(settings_stmt)
    b_settings = settings_res.scalar_one_or_none()
    if not b_settings:
        b_settings = BusinessSettings(org_id=org_id)
        db.add(b_settings)

    update_fields = [
        "industry",
        "website",
        "contact_phone",
        "contact_email",
        "business_address",
        "company_overview",
        "business_description",
        "business_services",
        "additional_info",
    ]
    for field in update_fields:
        val = getattr(payload, field)
        if val is not None:
            setattr(b_settings, field, val)

    await db.commit()
    await db.refresh(b_settings)
    await db.refresh(org)

    # Sync company profile to vector RAG
    try:
        await sync_service.sync_company_info(db, org_id, org.name, b_settings)
        await db.commit()
    except Exception as e:
        logger.error("Failed to sync company info to RAG: %s", e)

    return CompanyInfoResponse(
        business_name=org.name,
        industry=b_settings.industry,
        website=b_settings.website,
        contact_phone=b_settings.contact_phone,
        contact_email=b_settings.contact_email,
        business_address=b_settings.business_address,
        company_overview=b_settings.company_overview,
        business_description=b_settings.business_description,
        business_services=b_settings.business_services,
        additional_info=b_settings.additional_info,
        updated_at=b_settings.updated_at,
    )


# ===========================================================================
# 2. Products & Services Catalogue
# ===========================================================================
@router.get("/products", response_model=List[ProductServiceResponse])
async def list_products(
    category: Optional[str] = None,
    available_only: bool = False,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> List[ProductServiceResponse]:
    """List catalogue items for authenticated tenant."""
    org_id = TenantContext.get_current_tenant_id()
    stmt = select(ProductService).where(ProductService.org_id == org_id)
    if category:
        stmt = stmt.where(ProductService.category.ilike(category))
    if available_only:
        stmt = stmt.where(ProductService.is_available == True)
    stmt = stmt.order_by(ProductService.category, ProductService.name)
    res = await db.execute(stmt)
    return [ProductServiceResponse.model_validate(p) for p in res.scalars().all()]


@router.post("/products", response_model=ProductServiceResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductServiceCreateRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ProductServiceResponse:
    """Create a new catalogue item and automatically vectorize it for RAG."""
    org_id = TenantContext.get_current_tenant_id()
    product = ProductService(
        org_id=org_id,
        name=payload.name,
        description=payload.description,
        category=payload.category,
        features=payload.features,
        benefits=payload.benefits,
        price=payload.price,
        currency=payload.currency,
        pricing_type=payload.pricing_type,
        is_available=payload.is_available,
        specifications=payload.specifications,
    )
    db.add(product)
    await db.commit()
    await db.refresh(product)

    # Sync to vector RAG
    try:
        await sync_service.sync_product(db, product)
        await db.commit()
    except Exception as e:
        logger.error("Failed to sync product to RAG: %s", e)

    return ProductServiceResponse.model_validate(product)


@router.get("/products/{product_id}", response_model=ProductServiceResponse)
async def get_product(
    product_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ProductServiceResponse:
    org_id = TenantContext.get_current_tenant_id()
    stmt = select(ProductService).where(
        ProductService.id == product_id,
        ProductService.org_id == org_id,
    )
    res = await db.execute(stmt)
    product = res.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product or service not found")
    return ProductServiceResponse.model_validate(product)


@router.patch("/products/{product_id}", response_model=ProductServiceResponse)
async def update_product(
    product_id: uuid.UUID,
    payload: ProductServiceUpdateRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> ProductServiceResponse:
    org_id = TenantContext.get_current_tenant_id()
    stmt = select(ProductService).where(
        ProductService.id == product_id,
        ProductService.org_id == org_id,
    )
    res = await db.execute(stmt)
    product = res.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product or service not found")

    old_name = product.name
    for key, val in payload.model_dump(exclude_unset=True).items():
        setattr(product, key, val)

    await db.commit()
    await db.refresh(product)

    # If renamed, remove old vector doc
    if old_name != product.name:
        await sync_service.remove_entity_sync(db, org_id, f"Product/Service: {old_name}")

    # Re-sync to RAG
    try:
        await sync_service.sync_product(db, product)
        await db.commit()
    except Exception as e:
        logger.error("Failed to re-sync product to RAG: %s", e)

    return ProductServiceResponse.model_validate(product)


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: uuid.UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    org_id = TenantContext.get_current_tenant_id()
    stmt = select(ProductService).where(
        ProductService.id == product_id,
        ProductService.org_id == org_id,
    )
    res = await db.execute(stmt)
    product = res.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="Product or service not found")

    name = product.name
    await db.delete(product)
    await db.commit()

    # Clean vector RAG
    try:
        await sync_service.remove_entity_sync(db, org_id, f"Product/Service: {name}")
        await db.commit()
    except Exception as e:
        logger.error("Failed to remove product from RAG: %s", e)


# ===========================================================================
# 3. FAQs
# ===========================================================================
@router.get("/faqs", response_model=List[FAQResponse])
async def list_faqs(
    category: Optional[str] = None,
    active_only: bool = False,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> List[FAQResponse]:
    org_id = TenantContext.get_current_tenant_id()
    stmt = select(FAQ).where(FAQ.org_id == org_id)
    if category:
        stmt = stmt.where(FAQ.category.ilike(category))
    if active_only:
        stmt = stmt.where(FAQ.is_active == True)
    stmt = stmt.order_by(FAQ.category, FAQ.created_at)
    res = await db.execute(stmt)
    return [FAQResponse.model_validate(f) for f in res.scalars().all()]


@router.post("/faqs", response_model=FAQResponse, status_code=status.HTTP_201_CREATED)
async def create_faq(
    payload: FAQCreateRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> FAQResponse:
    org_id = TenantContext.get_current_tenant_id()
    faq = FAQ(
        org_id=org_id,
        question=payload.question,
        answer=payload.answer,
        category=payload.category,
        is_active=payload.is_active,
    )
    db.add(faq)
    await db.commit()
    await db.refresh(faq)

    # Sync to vector RAG
    try:
        await sync_service.sync_faq(db, faq)
        await db.commit()
    except Exception as e:
        logger.error("Failed to sync FAQ to RAG: %s", e)

    return FAQResponse.model_validate(faq)


@router.get("/faqs/{faq_id}", response_model=FAQResponse)
async def get_faq(
    faq_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> FAQResponse:
    org_id = TenantContext.get_current_tenant_id()
    stmt = select(FAQ).where(FAQ.id == faq_id, FAQ.org_id == org_id)
    res = await db.execute(stmt)
    faq = res.scalar_one_or_none()
    if not faq:
        raise HTTPException(status_code=404, detail="FAQ not found")
    return FAQResponse.model_validate(faq)


@router.patch("/faqs/{faq_id}", response_model=FAQResponse)
async def update_faq(
    faq_id: uuid.UUID,
    payload: FAQUpdateRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> FAQResponse:
    org_id = TenantContext.get_current_tenant_id()
    stmt = select(FAQ).where(FAQ.id == faq_id, FAQ.org_id == org_id)
    res = await db.execute(stmt)
    faq = res.scalar_one_or_none()
    if not faq:
        raise HTTPException(status_code=404, detail="FAQ not found")

    old_q = faq.question
    for key, val in payload.model_dump(exclude_unset=True).items():
        setattr(faq, key, val)

    await db.commit()
    await db.refresh(faq)

    if old_q != faq.question:
        await sync_service.remove_entity_sync(db, org_id, f"FAQ: {old_q[:50]}")

    try:
        await sync_service.sync_faq(db, faq)
        await db.commit()
    except Exception as e:
        logger.error("Failed to sync FAQ to RAG: %s", e)

    return FAQResponse.model_validate(faq)


@router.delete("/faqs/{faq_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_faq(
    faq_id: uuid.UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    org_id = TenantContext.get_current_tenant_id()
    stmt = select(FAQ).where(FAQ.id == faq_id, FAQ.org_id == org_id)
    res = await db.execute(stmt)
    faq = res.scalar_one_or_none()
    if not faq:
        raise HTTPException(status_code=404, detail="FAQ not found")

    title = f"FAQ: {faq.question[:50]}"
    await db.delete(faq)
    await db.commit()

    try:
        await sync_service.remove_entity_sync(db, org_id, title)
        await db.commit()
    except Exception as e:
        logger.error("Failed to remove FAQ from RAG: %s", e)


# ===========================================================================
# 4. Business Policies
# ===========================================================================
@router.get("/policies", response_model=List[BusinessPolicyResponse])
async def list_policies(
    policy_type: Optional[str] = None,
    active_only: bool = False,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> List[BusinessPolicyResponse]:
    org_id = TenantContext.get_current_tenant_id()
    stmt = select(BusinessPolicy).where(BusinessPolicy.org_id == org_id)
    if policy_type:
        stmt = stmt.where(BusinessPolicy.policy_type.ilike(policy_type))
    if active_only:
        stmt = stmt.where(BusinessPolicy.is_active == True)
    stmt = stmt.order_by(BusinessPolicy.policy_type, BusinessPolicy.title)
    res = await db.execute(stmt)
    return [BusinessPolicyResponse.model_validate(p) for p in res.scalars().all()]


@router.post("/policies", response_model=BusinessPolicyResponse, status_code=status.HTTP_201_CREATED)
async def create_policy(
    payload: BusinessPolicyCreateRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> BusinessPolicyResponse:
    org_id = TenantContext.get_current_tenant_id()
    policy = BusinessPolicy(
        org_id=org_id,
        policy_type=payload.policy_type,
        title=payload.title,
        content=payload.content,
        is_active=payload.is_active,
    )
    db.add(policy)
    await db.commit()
    await db.refresh(policy)

    # Sync to vector RAG
    try:
        await sync_service.sync_policy(db, policy)
        await db.commit()
    except Exception as e:
        logger.error("Failed to sync policy to RAG: %s", e)

    return BusinessPolicyResponse.model_validate(policy)


@router.get("/policies/{policy_id}", response_model=BusinessPolicyResponse)
async def get_policy(
    policy_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> BusinessPolicyResponse:
    org_id = TenantContext.get_current_tenant_id()
    stmt = select(BusinessPolicy).where(BusinessPolicy.id == policy_id, BusinessPolicy.org_id == org_id)
    res = await db.execute(stmt)
    policy = res.scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=404, detail="Business policy not found")
    return BusinessPolicyResponse.model_validate(policy)


@router.patch("/policies/{policy_id}", response_model=BusinessPolicyResponse)
async def update_policy(
    policy_id: uuid.UUID,
    payload: BusinessPolicyUpdateRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> BusinessPolicyResponse:
    org_id = TenantContext.get_current_tenant_id()
    stmt = select(BusinessPolicy).where(BusinessPolicy.id == policy_id, BusinessPolicy.org_id == org_id)
    res = await db.execute(stmt)
    policy = res.scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=404, detail="Business policy not found")

    old_title = policy.title
    for key, val in payload.model_dump(exclude_unset=True).items():
        setattr(policy, key, val)

    await db.commit()
    await db.refresh(policy)

    if old_title != policy.title:
        await sync_service.remove_entity_sync(db, org_id, f"Policy: {old_title}")

    try:
        await sync_service.sync_policy(db, policy)
        await db.commit()
    except Exception as e:
        logger.error("Failed to sync policy to RAG: %s", e)

    return BusinessPolicyResponse.model_validate(policy)


@router.delete("/policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_policy(
    policy_id: uuid.UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    org_id = TenantContext.get_current_tenant_id()
    stmt = select(BusinessPolicy).where(BusinessPolicy.id == policy_id, BusinessPolicy.org_id == org_id)
    res = await db.execute(stmt)
    policy = res.scalar_one_or_none()
    if not policy:
        raise HTTPException(status_code=404, detail="Business policy not found")

    title = f"Policy: {policy.title}"
    await db.delete(policy)
    await db.commit()

    try:
        await sync_service.remove_entity_sync(db, org_id, title)
        await db.commit()
    except Exception as e:
        logger.error("Failed to remove policy from RAG: %s", e)


# ===========================================================================
# 5. Document Ingestion
# ===========================================================================
@router.post("/documents/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    document_type: str = Form("general"),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    """Upload and vectorize a document (PDF, TXT, MD) with chunking and embeddings."""
    org_id = TenantContext.get_current_tenant_id()
    if document_type not in ("faq", "product_spec", "pricing", "policy", "general"):
        raise HTTPException(status_code=400, detail="Invalid document_type")

    file_bytes = await file.read()
    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    doc_title = title.strip() if title and title.strip() else file.filename or "Uploaded Document"

    try:
        doc = await ingestion_service.ingest_document(
            db=db,
            org_id=org_id,
            title=doc_title,
            file_bytes=file_bytes,
            filename=file.filename or "document.txt",
            document_type=document_type,
        )
        await db.commit()
        await db.refresh(doc)
        return DocumentResponse.model_validate(doc)
    except Exception as e:
        logger.error("Error during document ingestion: %s", e)
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/documents", response_model=List[DocumentResponse])
async def list_documents(
    document_type: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> List[DocumentResponse]:
    """List all knowledge documents for current tenant."""
    org_id = TenantContext.get_current_tenant_id()
    stmt = select(KnowledgeDocument).where(KnowledgeDocument.org_id == org_id)
    if document_type:
        stmt = stmt.where(KnowledgeDocument.document_type == document_type)
    stmt = stmt.order_by(KnowledgeDocument.created_at.desc())
    res = await db.execute(stmt)
    return [DocumentResponse.model_validate(d) for d in res.scalars().all()]


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete a document and all associated chunks."""
    org_id = TenantContext.get_current_tenant_id()
    deleted = await ingestion_service.delete_document(db, org_id, document_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")
    await db.commit()


@router.post("/documents/{document_id}/retry", response_model=DocumentResponse)
async def retry_document(
    document_id: uuid.UUID,
    file: Optional[UploadFile] = File(None),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    """Retry or re-index document parsing, chunking, and vector embedding."""
    org_id = TenantContext.get_current_tenant_id()
    new_bytes = None
    new_filename = None
    if file:
        new_bytes = await file.read()
        new_filename = file.filename

    try:
        doc = await ingestion_service.retry_document(
            db=db,
            org_id=org_id,
            document_id=document_id,
            new_file_bytes=new_bytes,
            new_filename=new_filename,
        )
        await db.commit()
        await db.refresh(doc)
        return DocumentResponse.model_validate(doc)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Error retrying document %s: %s", document_id, e)
        raise HTTPException(status_code=500, detail=str(e))


# ===========================================================================
# 6. Semantic RAG Query
# ===========================================================================
@router.post("/query", response_model=KnowledgeQueryResponse)
async def query_knowledge_base(
    payload: KnowledgeQueryRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeQueryResponse:
    """Execute semantic similarity search against pgvector knowledge chunks."""
    org_id = TenantContext.get_current_tenant_id()
    results = await retriever_service.search(
        db=db,
        org_id=org_id,
        query=payload.query,
        limit=payload.limit,
        score_threshold=payload.score_threshold,
        document_types=payload.document_types,
    )
    items = [
        KnowledgeSearchResultItem(
            chunk_id=r.chunk_id,
            document_id=r.document_id,
            document_title=r.document_title,
            document_type=r.document_type,
            content=r.content,
            score=r.score,
            token_count=r.token_count,
        )
        for r in results
    ]
    return KnowledgeQueryResponse(query=payload.query, count=len(items), results=items)
