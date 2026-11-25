"""Centralized application exception definitions and response schemas."""

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from fastapi import Request, status
from fastapi.responses import JSONResponse


class AppException(Exception):
    """Base class for all application-domain exceptions."""

    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_SERVER_ERROR",
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}


class EntityNotFoundError(AppException):
    """Raised when a requested resource does not exist."""

    def __init__(self, entity_name: str, identifier: Any):
        super().__init__(
            message=f"{entity_name} with identifier '{identifier}' was not found.",
            code="ENTITY_NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"entity": entity_name, "identifier": str(identifier)},
        )


class TenantAccessForbiddenError(AppException):
    """Raised when cross-tenant data access is attempted."""

    def __init__(self, message: str = "Cross-tenant access forbidden."):
        super().__init__(
            message=message,
            code="TENANT_ACCESS_FORBIDDEN",
            status_code=status.HTTP_403_FORBIDDEN,
        )


class ConflictError(AppException):
    """Raised when a resource state conflict occurs (e.g., booking collision)."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message=message,
            code="RESOURCE_CONFLICT",
            status_code=status.HTTP_409_CONFLICT,
            details=details,
        )


class DatabaseConnectionError(AppException):
    """Raised when database connectivity fails."""

    def __init__(self, message: str = "Database connection error."):
        super().__init__(
            message=message,
            code="DATABASE_UNAVAILABLE",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """Formats AppException into standardized JSON response."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        },
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Formats uncaught exceptions into secure standardized JSON response."""
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected server error occurred.",
                "details": {},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        },
    )
