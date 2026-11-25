"""FastAPI dependencies for authentication, role authorization, and tenant context binding."""

import uuid
from typing import Callable, List, Optional
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.core.database import get_db
from backend.app.core.exceptions import AppException
from backend.app.core.security import decode_token
from backend.app.core.tenant import TenantContext
from backend.app.models.organization import Organization
from backend.app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

# Role definitions mapping aliases
ROLE_HIERARCHY = {
    "owner": ["owner", "super_admin", "admin", "receptionist", "employee", "sales_employee"],
    "super_admin": ["owner", "super_admin", "admin", "receptionist", "employee", "sales_employee"],
    "admin": ["admin", "receptionist", "employee", "sales_employee"],
    "receptionist": ["receptionist", "employee", "sales_employee"],
    "employee": ["employee", "sales_employee"],
    "sales_employee": ["employee", "sales_employee"],
}


async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Authenticates the request, decodes JWT, and binds TenantContext."""
    raw_token = token
    if not raw_token and authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            raw_token = parts[1]

    if not raw_token:
        raise AppException(
            message="Missing authentication token. Please login.",
            code="AUTHENTICATION_REQUIRED",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    payload = decode_token(raw_token)
    if payload.get("type") == "refresh":
        raise AppException(
            message="Refresh tokens cannot be used to authenticate API requests. Please use an access token.",
            code="TOKEN_TYPE_INVALID",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    try:
        user_id = uuid.UUID(payload.get("sub"))
        org_id = uuid.UUID(payload.get("org_id"))
    except (ValueError, TypeError):
        raise AppException(
            message="Malformed authentication claims.",
            code="TOKEN_CLAIMS_INVALID",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    # Strictly bind the authenticated organization ID into the coroutine TenantContext
    TenantContext.set_current_tenant_id(org_id)

    # Fetch user from database ensuring active tenant match and active organization
    stmt = (
        select(User, Organization.is_active.label("org_is_active"))
        .join(Organization, Organization.id == User.org_id)
        .where(User.id == user_id, User.org_id == org_id)
        .execution_options(ignore_tenant_isolation=True)  # Auth lookup
    )
    result = await db.execute(stmt)
    row = result.first()

    if not row:
        raise AppException(
            message="User account associated with this token was not found.",
            code="USER_NOT_FOUND",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    user, org_is_active = row
    if not org_is_active:
        raise AppException(
            message="Organization account is deactivated. Access denied.",
            code="ORGANIZATION_DEACTIVATED",
            status_code=status.HTTP_403_FORBIDDEN,
        )

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Validates that the authenticated user account is active."""
    if not current_user.is_active:
        raise AppException(
            message="User account is deactivated. Please contact your organization administrator.",
            code="USER_DEACTIVATED",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    return current_user


def require_role(*allowed_roles: str) -> Callable:
    """Dependency factory enforcing that the authenticated user has one of the allowed roles.

    Automatically handles role inheritance (e.g., owner has all admin/receptionist permissions).
    """
    normalized_allowed: List[str] = []
    for r in allowed_roles:
        r_lower = r.lower()
        normalized_allowed.append(r_lower)
        if r_lower in ("owner", "super_admin"):
            normalized_allowed.extend(["owner", "super_admin"])
        elif r_lower in ("employee", "sales_employee"):
            normalized_allowed.extend(["employee", "sales_employee"])

    async def role_checker(
        current_user: User = Depends(get_current_active_user),
    ) -> User:
        user_role = current_user.role.lower()

        # Check if user role matches directly or through hierarchy
        has_permission = False
        if user_role in normalized_allowed:
            has_permission = True
        elif user_role in ("owner", "super_admin"):
            has_permission = True  # Owners inherit all roles
        elif user_role == "admin" and any(r in ("receptionist", "employee", "sales_employee") for r in normalized_allowed):
            has_permission = True  # Admins inherit staff roles

        if not has_permission:
            raise AppException(
                message=f"Access denied: Role '{current_user.role}' lacks permission for this action. Required: {list(allowed_roles)}.",
                code="INSUFFICIENT_PERMISSIONS",
                status_code=status.HTTP_403_FORBIDDEN,
            )
        return current_user

    return role_checker


# Specific shorthand role dependencies
require_owner = require_role("owner", "super_admin")
require_admin = require_role("owner", "super_admin", "admin")
require_receptionist = require_role("owner", "super_admin", "admin", "receptionist")
require_employee = require_role("owner", "super_admin", "admin", "receptionist", "employee", "sales_employee")


async def get_current_org(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Organization:
    """Returns the Organization entity corresponding to the authenticated user's tenant."""
    stmt = (
        select(Organization)
        .where(Organization.id == current_user.org_id)
        .execution_options(ignore_tenant_isolation=True)
    )
    result = await db.execute(stmt)
    org = result.scalar_one_or_none()
    if not org or not org.is_active:
        raise AppException(
            message="Organization not found or inactive.",
            code="ORGANIZATION_NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return org
