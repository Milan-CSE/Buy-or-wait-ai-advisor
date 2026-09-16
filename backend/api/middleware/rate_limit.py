"""
backend/api/middleware/rate_limit.py

Sliding-window HTTP rate limiting middleware with category quotas and RFC 7807 rejection.
"""
from __future__ import annotations
import json
import uuid
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from backend.api.config import settings
from backend.auth.rate_limiter import get_rate_limiter


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip rate limiting on docs, openapi, and health
        path = request.url.path
        if path in ("/docs", "/redoc", "/openapi.json", "/api/v1/health") or request.method == "OPTIONS":
            return await call_next(request)

        # Determine client identifier
        client_ip = "127.0.0.1"
        if request.client:
            client_ip = request.client.host
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()

        # Check authorization token if present for tenant-level rate limiting
        auth_header = request.headers.get("Authorization", "")
        token_id = ""
        if auth_header.startswith("Bearer "):
            token_id = auth_header[7:].strip()[:16]  # Use token prefix as part of bucket key

        bucket_id = f"{client_ip}:{token_id}" if token_id else client_ip

        # Determine category quota
        if path.startswith("/api/v1/auth"):
            limit = settings.RATE_LIMIT_AUTH
            category = "auth"
        elif path.startswith("/api/v1/purchases/evaluate"):
            limit = settings.RATE_LIMIT_EVALUATE
            category = "evaluate"
        elif path.startswith("/api/v1/imports"):
            limit = settings.RATE_LIMIT_UPLOAD
            category = "upload"
        else:
            limit = settings.RATE_LIMIT_GENERAL
            category = "general"

        limiter = get_rate_limiter()
        res = limiter.check(f"{category}:{bucket_id}", limit=limit, window_seconds=60)

        if not res.allowed:
            req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
            return JSONResponse(
                status_code=429,
                content={
                    "type": "https://api.buyorwait.com/errors/rate-limit-exceeded",
                    "title": "Too Many Requests",
                    "status": 429,
                    "detail": f"Rate limit exceeded for category '{category}'. Please retry in {res.retry_after} seconds.",
                    "instance": path,
                    "code": "RATE_LIMIT_EXCEEDED",
                    "retry_after": res.retry_after,
                    "request_id": req_id,
                },
                headers={
                    "Retry-After": str(res.retry_after),
                    "X-RateLimit-Limit": str(res.limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(res.reset_seconds),
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(res.limit)
        response.headers["X-RateLimit-Remaining"] = str(res.remaining)
        response.headers["X-RateLimit-Reset"] = str(res.reset_seconds)
        return response
