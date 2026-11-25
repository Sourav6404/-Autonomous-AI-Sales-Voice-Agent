"""Health check schema models."""

from datetime import datetime
from typing import Dict, Literal, Optional
from pydantic import BaseModel, Field


class ServiceStatus(BaseModel):
    """Component service status report."""

    status: Literal["healthy", "unhealthy", "degraded"]
    latency_ms: Optional[float] = None
    details: Optional[str] = None


class HealthCheckResponse(BaseModel):
    """Liveness probe response."""

    status: Literal["ok", "error"]
    timestamp: datetime
    app: str
    environment: str


class ReadinessCheckResponse(BaseModel):
    """Readiness probe response including database connectivity."""

    status: Literal["ready", "not_ready"]
    timestamp: datetime
    services: Dict[str, ServiceStatus]
