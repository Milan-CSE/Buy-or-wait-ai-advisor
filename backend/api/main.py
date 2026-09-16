"""
backend/api/main.py

Hardened production FastAPI application for Buy or Wait? financial decision engine.
Configures routers, CORS, observability, security headers, rate limiting, and RFC 7807 exception handlers.
"""
from __future__ import annotations
import logging
import uuid
from fastapi import FastAPI, HTTPException, Request, status
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.api.config import settings
from backend.api.middleware.observability import ObservabilityMiddleware
from backend.api.middleware.rate_limit import RateLimitMiddleware
from backend.api.middleware.security import SecurityHeadersMiddleware
from backend.api.routers import (
    accounts_router,
    auth_router,
    decisions_router,
    health_router,
    imports_router,
    profile_router,
    purchases_router,
    transactions_router,
)
from backend.database.repositories.base import TenantAccessError
from backend.ingestion.security import FileOversizedError, IngestionSecurityError
from backend.ingestion.service import DuplicateFileError
from backend.services.errors import (
    DataInsufficientError,
    InvalidPurchaseError,
    ServiceError,
)

logger = logging.getLogger("buyorwait.api")


def create_app() -> FastAPI:
    """Application factory creating hardened production FastAPI instance."""
    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.API_VERSION,
        description=(
            "Enterprise-grade decision support REST API evaluating purchase affordability, "
            "reconciling multi-account cash flows, and quantifying P90 stress risk."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # 1. Observability, Security, & Rate Limiting Middleware
    # Starlette executes middleware in reverse order of addition:
    # RateLimit -> SecurityHeaders -> Observability -> App
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(ObservabilityMiddleware)

    # 2. Hardened CORS Configuration (Never allow wildcard with credentials)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-Correlation-ID", "X-Idempotency-Key"],
    )

    # 3. RFC 7807 Standardized Exception Handlers
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "type": f"https://api.buyorwait.com/errors/http-{exc.status_code}",
                "title": exc.detail if isinstance(exc.detail, str) else "HTTP Exception",
                "status": exc.status_code,
                "detail": str(exc.detail),
                "instance": request.url.path,
                "code": f"HTTP_{exc.status_code}",
                "request_id": req_id,
            },
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        invalid_params = []
        for err in exc.errors():
            invalid_params.append({
                "field": ".".join(str(loc) for loc in err.get("loc", []) if loc != "body"),
                "message": err.get("msg", ""),
                "type": err.get("type", ""),
            })
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "type": "https://api.buyorwait.com/errors/validation-error",
                "title": "Unprocessable Entity",
                "status": 422,
                "detail": "Request payload failed validation constraints.",
                "instance": request.url.path,
                "code": "VALIDATION_FAILED",
                "invalid_params": invalid_params,
                "request_id": req_id,
            },
        )

    @app.exception_handler(DataInsufficientError)
    async def data_insufficient_handler(request: Request, exc: DataInsufficientError):
        req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "type": "https://api.buyorwait.com/errors/data-insufficient",
                "title": "Data Insufficient",
                "status": 422,
                "detail": exc.reason,
                "instance": request.url.path,
                "code": "DATA_INSUFFICIENT",
                "error": {
                    "code": "DATA_INSUFFICIENT",
                    "reason": exc.reason,
                    "affected_data": exc.affected_data,
                    "user_action_required": exc.user_action_required,
                },
                "request_id": req_id,
            },
        )

    @app.exception_handler(InvalidPurchaseError)
    async def invalid_purchase_handler(request: Request, exc: InvalidPurchaseError):
        req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "type": "https://api.buyorwait.com/errors/invalid-purchase",
                "title": "Invalid Purchase Proposal",
                "status": 422,
                "detail": exc.message,
                "instance": request.url.path,
                "code": "INVALID_PURCHASE",
                "request_id": req_id,
            },
        )

    @app.exception_handler(TenantAccessError)
    async def tenant_access_handler(request: Request, exc: TenantAccessError):
        req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        logger.warning(
            "unauthorized_cross_tenant_access_attempt",
            extra={"request_id": req_id, "path": request.url.path, "error": str(exc)},
        )
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "type": "https://api.buyorwait.com/errors/not-found",
                "title": "Resource Not Found",
                "status": 404,
                "detail": "The requested resource does not exist.",
                "instance": request.url.path,
                "code": "RESOURCE_NOT_FOUND",
                "request_id": req_id,
            },
        )

    @app.exception_handler(DuplicateFileError)
    async def duplicate_file_handler(request: Request, exc: DuplicateFileError):
        req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "type": "https://api.buyorwait.com/errors/duplicate-file",
                "title": "Duplicate Statement File",
                "status": 409,
                "detail": str(exc),
                "instance": request.url.path,
                "code": "DUPLICATE_FILE",
                "sha256": getattr(exc, "sha256", ""),
                "request_id": req_id,
            },
        )

    @app.exception_handler(FileOversizedError)
    async def file_oversized_handler(request: Request, exc: FileOversizedError):
        req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        return JSONResponse(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            content={
                "type": "https://api.buyorwait.com/errors/file-too-large",
                "title": "Payload Too Large",
                "status": 413,
                "detail": str(exc),
                "instance": request.url.path,
                "code": "FILE_TOO_LARGE",
                "request_id": req_id,
            },
        )

    @app.exception_handler(IngestionSecurityError)
    async def ingestion_security_handler(request: Request, exc: IngestionSecurityError):
        req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        return JSONResponse(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            content={
                "type": "https://api.buyorwait.com/errors/unsupported-media-type",
                "title": "Unsupported Media Type",
                "status": 415,
                "detail": str(exc),
                "instance": request.url.path,
                "code": "INVALID_FILE_TYPE",
                "request_id": req_id,
            },
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        # Log error internally with stack trace, but never leak internals in HTTP response
        logger.error("unhandled_server_error", exc_info=exc, extra={"request_id": req_id})
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "type": "https://api.buyorwait.com/errors/internal-error",
                "title": "Internal Server Error",
                "status": 500,
                "detail": "An unexpected error occurred. Please contact support with the request ID.",
                "instance": request.url.path,
                "code": "INTERNAL_SERVER_ERROR",
                "request_id": req_id,
            },
        )

    # 4. Versioned API Routers
    app.include_router(auth_router, prefix=settings.API_V1_STR)
    app.include_router(health_router, prefix=settings.API_V1_STR)
    app.include_router(profile_router, prefix=settings.API_V1_STR)
    app.include_router(accounts_router, prefix=settings.API_V1_STR)
    app.include_router(transactions_router, prefix=settings.API_V1_STR)
    app.include_router(imports_router, prefix=settings.API_V1_STR)
    app.include_router(purchases_router, prefix=settings.API_V1_STR)
    app.include_router(decisions_router, prefix=settings.API_V1_STR)

    return app


app = create_app()
