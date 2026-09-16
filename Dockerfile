# syntax=docker/dockerfile:1
# Hardened multi-stage production Dockerfile for Buy or Wait? API
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build dependencies only in builder stage
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install python wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Final minimal runtime container
FROM python:3.11-slim AS runner

WORKDIR /app

# Install minimal runtime libraries (libpq)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create unprivileged non-root user and group (UID/GID 10001)
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /sbin/nologin -M appuser

# Copy installed wheels from builder to appuser home
COPY --from=builder /root/.local /home/appuser/.local
ENV PATH=/home/appuser/.local/bin:$PATH
ENV PYTHONPATH=/app

# Copy application source code
COPY --chown=appuser:appgroup backend /app/backend
COPY --chown=appuser:appgroup buyorwait_engine /app/buyorwait_engine
COPY --chown=appuser:appgroup code /app/code
COPY --chown=appuser:appgroup v3 /app/v3
COPY --chown=appuser:appgroup dataset /app/dataset

# Create quarantine directory owned by appuser
RUN mkdir -p /app/backend/ingestion/quarantine && \
    chown -R appuser:appgroup /app/backend/ingestion/quarantine

# Drop privileges to unprivileged user
USER 10001:10001

# Expose explicit HTTP port
EXPOSE 8000

# Health check without root tools
HEALTHCHECK --interval=15s --timeout=3s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

# Start hardened uvicorn server
CMD ["uvicorn", "backend.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--no-access-log"]
