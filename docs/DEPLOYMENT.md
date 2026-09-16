# Deployment Guide — Buy or Wait? Production API

> [!WARNING]
> **DEPLOYMENT-READY — MANUAL CLOUD STEP REMAINS**
> The application code, tests, and configuration are verified and ready for production deployment. However, the final deployment step requires manual action by an administrator with access to the Render.com account, as the agent does not possess cloud provider credentials.

## Target Platform: Render.com

### Why Render?

| Criterion | Render | Railway | Fly.io |
|---|---|---|---|
| Persistent disk for quarantine files | Built-in managed disks | Ephemeral only | Volumes (more complex) |
| PostgreSQL managed service | Built-in | Built-in | Separate add-on |
| Environment variable management | Dashboard + secret groups | Dashboard | CLI + dashboard |
| Zero-downtime deploys | Health-check gated | Yes | Yes |
| Docker deploy from Git | Yes | Yes | Yes |

Render is selected because it provides a managed PostgreSQL service, persistent disks for file quarantine, and health-check-gated deploys that map directly to `/api/v1/health/liveness`.

---

## 1. Prerequisites

- Docker installed locally (for local testing)
- Render account at https://render.com
- Repository pushed to GitHub or GitLab
- Environment variables prepared (see §3)

---

## 2. Local Development Quick Start

```bash
git clone <repo-url>
cd hacker_rank_projectt
cp .env.example .env
# Edit .env — set DATABASE_URL and JWT_SECRET_KEY at minimum

# Start everything
docker compose up --build

# Run migrations (first time or after schema changes)
alembic upgrade head

# Verify health
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/api/v1/health/liveness
curl http://localhost:8000/api/v1/health/readiness

# Run all tests
python -m pytest backend/tests/ buyorwait_engine/tests/ v3/tests/ -q
```

---

## 3. Required Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | Full PostgreSQL connection string |
| `JWT_SECRET_KEY` | Yes | HMAC-SHA256 signing key (min 32 chars) |
| `ENVIRONMENT` | Yes | `production` / `development` / `test` |
| `RATE_LIMIT_AUTH` | No | Auth requests/minute per IP (default: 5) |
| `RATE_LIMIT_EVALUATE` | No | Evaluate requests/minute per user (default: 30) |
| `RATE_LIMIT_UPLOAD` | No | Upload requests/minute per user (default: 10) |
| `RATE_LIMIT_GENERAL` | No | General requests/minute per IP (default: 120) |

**Fail-fast behavior**: The application validates `DATABASE_URL` and `JWT_SECRET_KEY` at startup. Missing or malformed values cause immediate exit with a clear error.

Generate a secure JWT key:
```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

---

## 4. Render Deployment Steps

### Step 1: Create PostgreSQL Database
- Render Dashboard → New → PostgreSQL
- Name: `buyorwait-db`, Plan: Starter, PostgreSQL version: 16
- Save the **Internal Database URL**

### Step 2: Create Web Service
- New → Web Service → connect repository
- Runtime: Docker, Dockerfile path: `./Dockerfile`
- Health Check Path: `/api/v1/health/liveness`
- Pre-deploy command: `alembic upgrade head`

### Step 3: Set Environment Variables
```
DATABASE_URL=<Internal Database URL from step 1>
JWT_SECRET_KEY=<64-character random key>
ENVIRONMENT=production
RATE_LIMIT_AUTH=5
RATE_LIMIT_EVALUATE=30
RATE_LIMIT_UPLOAD=10
RATE_LIMIT_GENERAL=120
```

### Step 4: Configure Persistent Disk
- Web Service → Disks tab
- Mount path: `/app/backend/ingestion/quarantine`
- Size: 1 GB minimum

### Step 5: Deploy
Push to main branch. Render auto-deploys. Monitor health check logs.

---

## 5. Database Migration Lifecycle

```bash
# Apply all migrations
alembic upgrade head

# Roll back one step
alembic downgrade -1

# Roll back to empty schema
alembic downgrade base

# Check current state
alembic current

# Verify tables after fresh migration
python -c "
from backend.database.session import engine
from sqlalchemy import inspect
print(sorted(inspect(engine).get_table_names()))
"
```

Expected tables: `alembic_version`, `audit_events`, `bank_accounts`, `decisions`, `financial_profiles`, `idempotency_records`, `import_batches`, `purchase_proposals`, `revoked_tokens`, `transactions`, `users`

---

## 6. Backup and Recovery

- **Render PostgreSQL**: Automated daily backups on Starter plan
- **Manual backup**: `pg_dump $DATABASE_URL > backup_$(date +%Y%m%d_%H%M%S).sql`
- **Restore**: `psql $DATABASE_URL < backup_20260915_120000.sql`
- **Point-in-time recovery**: Available on Standard plan and above

---

## 7. Scaling

The system is a modular monolith (single process + single database) targeting 10-50 concurrent users.

| Resource | Starter Config | Scale When |
|---|---|---|
| API instances | 1 x 512 MB RAM | P95 latency > 2s |
| PostgreSQL | Starter (1 GB RAM) | Query times > 100ms |
| Quarantine disk | 1 GB | Usage > 80% |

---

## 8. Production Security Checklist

- [ ] `JWT_SECRET_KEY` is at least 64 random characters
- [ ] `DATABASE_URL` uses SSL (`?sslmode=require`) in production
- [ ] `ENVIRONMENT=production` is set
- [ ] Persistent disk configured for quarantine (not ephemeral)
- [ ] No `.env` file committed to source control
- [ ] `alembic upgrade head` runs before new version serves traffic
- [ ] Rate limits configured appropriately

---

## 9. Deployment Smoke Test

```bash
BASE_URL=https://your-app.onrender.com

# 1. Health endpoints
curl -s $BASE_URL/api/v1/health | jq .
curl -s $BASE_URL/api/v1/health/liveness | jq .
curl -s $BASE_URL/api/v1/health/readiness | jq .

# 2. Register and login
curl -s -X POST $BASE_URL/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"smoke@test.com","password":"SmokeTest1234!","full_name":"Smoke Test"}' | jq .

TOKEN=$(curl -s -X POST $BASE_URL/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"smoke@test.com","password":"SmokeTest1234!"}' | jq -r .access_token)

# 3. Authenticated profile access
curl -s $BASE_URL/api/v1/profile \
  -H "Authorization: Bearer $TOKEN" | jq .

# 4. Metrics scrape
curl -s $BASE_URL/api/v1/metrics | head -20

# 5. Invalid token rejection (must return 401)
curl -s $BASE_URL/api/v1/profile \
  -H "Authorization: Bearer invalid_token" | jq .status
```
