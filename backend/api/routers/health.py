"""
backend/api/routers/health.py
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.api.config import settings
from backend.api.dependencies import get_db
from backend.api.schemas.health import HealthResponse, LivenessResponse, ReadinessResponse
from backend.observability.metrics import get_metrics

router = APIRouter(tags=["Health & Observability"])


@router.get("/health", response_model=HealthResponse, summary="Service health check")
def get_health() -> HealthResponse:
    """Returns runtime health, API version, engine version, and calibration version."""
    return HealthResponse(
        status="healthy",
        api_version=settings.API_VERSION,
        engine_version=settings.ENGINE_VERSION,
        risk_calibration_version=settings.CALIBRATION_VERSION,
        timestamp=datetime.now(timezone.utc),
    )


@router.get("/health/liveness", response_model=LivenessResponse, summary="Kubernetes liveness probe")
def get_liveness() -> LivenessResponse:
    """Simple shallow probe confirming HTTP process is alive."""
    return LivenessResponse(
        status="alive",
        timestamp=datetime.now(timezone.utc),
    )


@router.get("/health/readiness", response_model=ReadinessResponse, summary="Kubernetes readiness probe")
def get_readiness(session: Session = Depends(get_db)) -> ReadinessResponse:
    """Deep readiness probe verifying critical dependencies including PostgreSQL connectivity."""
    db_ok = False
    try:
        session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    now = datetime.now(timezone.utc)
    if db_ok:
        return ReadinessResponse(
            status="ready",
            database="connected",
            dependencies={"database": "healthy"},
            timestamp=now,
        )
    else:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unready",
                "database": "disconnected",
                "dependencies": {"database": "unreachable"},
                "timestamp": now.isoformat(),
            },
        )


@router.get("/metrics", response_class=PlainTextResponse, summary="Prometheus metrics scrape endpoint")
def get_prometheus_metrics() -> str:
    """Returns operational metrics in Prometheus text format."""
    return get_metrics().to_prometheus()
