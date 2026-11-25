"""Health and readiness check endpoints."""

import time
from datetime import datetime, timezone
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from backend.app.core.config import settings
from backend.app.core.database import check_database_connection
from backend.app.schemas.health import HealthCheckResponse, ReadinessCheckResponse, ServiceStatus

router = APIRouter(tags=["Health"])


@router.get(
    "/health/live",
    response_model=HealthCheckResponse,
    summary="Application Liveness Probe",
    description="Returns 200 OK if the application process is running and accepting HTTP requests.",
)
async def liveness_probe() -> HealthCheckResponse:
    return HealthCheckResponse(
        status="ok",
        timestamp=datetime.now(timezone.utc),
        app=settings.APP_NAME,
        environment=settings.APP_ENV,
    )


@router.get(
    "/health/ready",
    response_model=ReadinessCheckResponse,
    responses={
        200: {"description": "All backend dependencies are healthy and ready."},
        503: {"description": "One or more critical dependencies (e.g. database) are unavailable."},
    },
    summary="Application Readiness Probe",
    description="Validates that database connectivity is active and ready for transaction processing.",
)
async def readiness_probe():
    start_time = time.perf_counter()
    db_connected = await check_database_connection()
    latency_ms = round((time.perf_counter() - start_time) * 1000, 2)

    db_status = ServiceStatus(
        status="healthy" if db_connected else "unhealthy",
        latency_ms=latency_ms if db_connected else None,
        details="PostgreSQL connection active" if db_connected else "Unable to reach database",
    )

    payload = ReadinessCheckResponse(
        status="ready" if db_connected else "not_ready",
        timestamp=datetime.now(timezone.utc),
        services={"database": db_status},
    )

    if not db_connected:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=payload.model_dump(mode="json"),
        )

    return payload
