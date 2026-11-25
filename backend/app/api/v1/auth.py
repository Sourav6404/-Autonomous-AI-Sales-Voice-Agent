"""Authentication and User Lifecycle Router."""

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import get_current_active_user, oauth2_scheme
from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.core.security import (
    PasswordHasher,
    RedisTokenBlacklist,
    TokenBlacklist,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from backend.app.core.tenant import TenantContext
from backend.app.models.ai_availability import AIAvailability
from backend.app.models.business_settings import BusinessSettings
from backend.app.models.organization import Organization
from backend.app.models.user import User
from backend.app.schemas.auth import (
    AuthResponse,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = None


def _slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    slug = re.sub(r"[-\s]+", "-", slug)
    return slug[:80] or f"org-{uuid.uuid4().hex[:8]}"


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register new organization and initial owner",
)
async def register_organization(
    payload: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    """Register a new tenant organization and initial owner account."""
    # Check if user email already exists
    existing_user_query = select(User).where(User.email == payload.email.lower().strip())
    existing_user_res = await db.execute(existing_user_query)
    if existing_user_res.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email address already exists.",
        )

    # Determine slug
    candidate_slug = payload.org_slug.strip().lower() if payload.org_slug else _slugify(payload.org_name)
    existing_slug_res = await db.execute(select(Organization).where(Organization.slug == candidate_slug))
    if existing_slug_res.scalar_one_or_none():
        candidate_slug = f"{candidate_slug}-{uuid.uuid4().hex[:6]}"

    # 1. Create Organization
    org = Organization(
        name=payload.org_name.strip(),
        slug=candidate_slug,
        default_timezone=payload.timezone,
        is_active=True,
    )
    db.add(org)
    await db.flush()

    # 2. Create Owner User
    hashed_pwd = PasswordHasher.hash(payload.password)
    owner = User(
        org_id=org.id,
        email=payload.email.lower().strip(),
        password_hash=hashed_pwd,
        full_name=payload.full_name.strip(),
        role="owner",
        phone_number=payload.phone_number.strip() if payload.phone_number else None,
        is_active=True,
    )
    db.add(owner)
    await db.flush()

    # 3. Create default BusinessSettings
    business_settings = BusinessSettings(
        org_id=org.id,
        primary_language="en",
        enable_multilingual=True,
        voice_id="sonic-english-1",
        after_hours_behavior="ai_voicemail",
        holiday_behavior="holiday_greeting",
        max_call_duration_seconds=900,
        recording_consent_required=True,
        contact_phone=payload.phone_number,
        contact_email=payload.email,
        business_description=f"Receptionist settings for {org.name}",
    )
    db.add(business_settings)

    # 4. Create default AIAvailability
    ai_avail = AIAvailability(
        org_id=org.id,
        status="online",
        auto_schedule_enabled=True,
        emergency_closure_active=False,
    )
    db.add(ai_avail)

    await db.commit()
    await db.refresh(owner)
    await db.refresh(org)

    # Generate JWT tokens
    access_token = create_access_token(
        subject=str(owner.id),
        org_id=str(org.id),
        role=owner.role,
        email=owner.email,
    )
    refresh_token = create_refresh_token(
        subject=str(owner.id),
        org_id=str(org.id),
    )

    return AuthResponse(
        user=UserResponse.model_validate(owner),
        org_id=org.id,
        org_name=org.name,
        tokens=TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        ),
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Authenticate user and return JWT tokens",
)
async def login(
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Authenticate with email and password."""
    user_query = select(User).where(User.email == payload.email.lower().strip())
    user_res = await db.execute(user_query)
    user = user_res.scalar_one_or_none()

    if not user or not PasswordHasher.verify(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated",
        )

    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()

    access_token = create_access_token(
        subject=str(user.id),
        org_id=str(user.org_id),
        role=user.role,
        email=user.email,
    )
    refresh_token = create_refresh_token(
        subject=str(user.id),
        org_id=str(user.org_id),
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token using valid refresh token",
)
async def refresh_token(
    payload: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Issue a new access token and refresh token from a valid refresh token."""
    decoded = decode_token(payload.refresh_token)
    if not decoded:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    if decoded.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token provided is not a refresh token",
        )

    user_id = decoded.get("sub")
    user_query = select(User).where(User.id == uuid.UUID(user_id))
    user_res = await db.execute(user_query)
    user = user_res.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    # Enforce single-use refresh token rotation: invalidate the used refresh token immediately
    RedisTokenBlacklist.revoke_token(payload.refresh_token)

    new_access_token = create_access_token(
        subject=str(user.id),
        org_id=str(user.org_id),
        role=user.role,
        email=user.email,
    )
    new_refresh_token = create_refresh_token(
        subject=str(user.id),
        org_id=str(user.org_id),
    )

    return TokenResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_200_OK,
    summary="Revoke access token and logout",
)
async def logout(
    payload: Optional[LogoutRequest] = None,
    token: str = Depends(oauth2_scheme),
    current_user: User = Depends(get_current_active_user),
) -> Dict[str, str]:
    """Invalidate current bearer token and optional refresh token via token revocation blacklist."""
    RedisTokenBlacklist.revoke_token(token)
    if payload and payload.refresh_token:
        RedisTokenBlacklist.revoke_token(payload.refresh_token)
    return {"message": "Successfully logged out"}


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current authenticated user profile",
)
async def get_me(
    current_user: User = Depends(get_current_active_user),
) -> UserResponse:
    """Return sanitized profile of current authenticated user."""
    return UserResponse.model_validate(current_user)
