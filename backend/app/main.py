"""FastAPI main application entry point."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.app.api.v1.router import api_v1_router
from backend.app.core.config import settings
from backend.app.core.database import check_database_connection
from backend.app.core.tenant import TenantContext
from backend.app.core.exceptions import (
    AppException,
    app_exception_handler,
    generic_exception_handler,
)
from backend.app.core.logging import logger, setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup and shutdown lifecycle management."""
    # Setup structured logging
    setup_logging(log_level=settings.LOG_LEVEL, log_format=settings.LOG_FORMAT)
    logger.info(
        f"Starting {settings.APP_NAME} in '{settings.APP_ENV}' environment",
        extra={"app": settings.APP_NAME, "env": settings.APP_ENV},
    )

    # Initial database connection verification
    db_ok = await check_database_connection()
    if db_ok:
        logger.info("Database connectivity established successfully.")
    else:
        logger.warning("Initial database connectivity check failed. Awaiting DB container.")

    yield

    logger.info("Shutting down FortiSales AI application.")
    from backend.app.core.database import engine
    await engine.dispose()


def create_application() -> FastAPI:
    """Factory creating and configuring the FastAPI instance."""
    app = FastAPI(
        title=settings.APP_NAME,
        version="1.0.0",
        description="Autonomous AI Sales Voice Agent - Enterprise Backend API",
        docs_url="/docs" if settings.DEBUG or settings.APP_ENV != "production" else None,
        redoc_url="/redoc" if settings.DEBUG or settings.APP_ENV != "production" else None,
        openapi_url="/openapi.json" if settings.DEBUG or settings.APP_ENV != "production" else None,
        lifespan=lifespan,
    )

    # CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.DEBUG else settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request-Scoped Tenant Context Lifecycle Middleware
    @app.middleware("http")
    async def tenant_context_lifecycle_middleware(request, call_next):
        try:
            return await call_next(request)
        finally:
            TenantContext.clear()

    # Centralized Exception Handlers
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)

    # API Routers
    app.include_router(api_v1_router, prefix=settings.API_V1_PREFIX)

    return app


app = create_application()
