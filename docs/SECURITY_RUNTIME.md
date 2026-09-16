# Security Architecture & Operations Guide: Buy or Wait?

**Version**: 1.0.0 (Milestone 6 Hardened)  
**Target Environment**: Commercial Deployment (Single/Multi-Tenant Cloud or On-Premise)  
**Classification**: Internal Technical Documentation  

---

## 1. Threat Model & Risk Matrix

We conducted a threat modeling exercise evaluating all attack surfaces across the application, API, persistence, and execution boundaries.

| Asset | Threat | Attack Surface | Control Implemented | Risk Level |
|---|---|---|---|:---:|
| **User Identity & Passwords** | Credential stuffing, brute-force dictionary attacks, password database compromise | `POST /api/v1/auth/login`, `POST /api/v1/auth/register` | OWASP-recommended **Argon2id** (`m=64MB, t=2, p=1`), per-hash cryptographic salt, constant-time verification, strict complexity validation (min 8 chars, Aa1!). | **CRITICAL** (Mitigated) |
| **Session Authentication** | Token forgery, replay after logout, long-lived token hijacking | Bearer Authorization header across all `/api/v1/` routes | Cryptographically signed HMAC-SHA256 JWT access tokens, 15-minute short lifetime, explicit claims (`sub`, `jti`, `iss`, `aud`, `exp`), and database-backed revocation blacklist. | **CRITICAL** (Mitigated) |
| **Financial Isolation** | Cross-tenant account/transaction/decision snooping or modification | Resource routes (`/accounts/{id}`, `/imports/{id}`, `/decisions/{id}`) | Strict tenant-scoped repositories (`tenant_id == current_user.id`). Cross-tenant access fails safely with **404 Not Found** to prevent resource ID enumeration. | **HIGH** (Mitigated) |
| **Decision Core Solvency** | False precision, data spoofing, injection of unsupported future income | `POST /api/v1/purchases/evaluate` | `DataQualityEvaluator` gating: requires >= 3 transactions across >= 14 days, non-negative buffer, non-stale balance (<=90d). Returns RFC 7807 `422 DATA_INSUFFICIENT` without guessing. | **HIGH** (Mitigated) |
| **Engine Availability** | Denial of Service via simulation spam or batch upload exhaustion | API endpoints | Application-level sliding-window rate limiter: Auth (5/min), Purchases (30/min), Uploads (10/min), General (120/min). Returns `429 Too Many Requests` with `Retry-After`. | **HIGH** (Mitigated) |
| **Statement Uploads** | Remote code execution, zip bombs, binary executables, directory traversal | `POST /api/v1/imports` | Multi-tier validation: 10MB size limit, extension whitelist (`.csv`, `.txt`, `.tsv`), binary magic-byte rejection (PE, ELF, Mach-O, ZIP, RAR, PDF), filename sanitization, UUID quarantine isolation. | **HIGH** (Mitigated) |
| **Sensitive Metadata** | Information disclosure via stack traces, server banners, or cache leakage | Error handlers, HTTP response headers | Standard RFC 7807 problem details hiding internal tracebacks/SQL. Strict security headers (`nosniff`, `DENY`, `HSTS`, `CSP: default-src 'none'`) and `Cache-Control: no-store` on financial endpoints. | **MEDIUM** (Mitigated) |
| **Secrets & Keys** | Hardcoded secrets committed to git or exposed via logs | `.env`, configuration classes, audit events | Strict environment profiles (`development`, `testing`, `production`). In production, startup aborts if `JWT_SECRET_KEY` is default/weak or CORS is wildcard. Zero secret logging in audit events. | **HIGH** (Mitigated) |

---

## 2. Authentication Architecture

### 2.1 Password Hashing (Argon2id)
- **Algorithm**: Argon2id (`argon2.Type.ID`, Version 19).
- **Parameters**:
  - Memory cost ($m$): $65536\text{ KB}$ ($64\text{ MB}$)
  - Time cost ($t$): $2\text{ iterations}$
  - Parallelism ($p$): $1\text{ thread}$
  - Hash length: $32\text{ bytes}$
- **Salt**: 16 cryptographically secure random bytes generated uniquely per hash.
- **Verification**: Constant-time execution via `argon2.PasswordHasher.verify`.

### 2.2 Password Complexity Policy
All candidate passwords on `POST /api/v1/auth/register` must satisfy:
1. Minimum length: **8 characters** (recommended 12+).
2. At least one lowercase letter (`[a-z]`).
3. At least one uppercase letter (`[A-Z]`).
4. At least one numeric digit (`[0-9]`).
5. At least one special symbol (`[!@#$%^&*(),.?":{}|<>-=_+[]/;`~]`).

### 2.3 JWT Token Specification
- **Format**: RFC 7519 JSON Web Token.
- **Signing Algorithm**: HMAC-SHA256 (`HS256`).
- **Secret Key**: `JWT_SECRET_KEY` injected from environment (minimum 32 characters in production).
- **Default TTL**: **15 minutes** (`ACCESS_TOKEN_EXPIRE_MINUTES=15`).
- **Standard Claims**:
  ```json
  {
    "sub": "b8f04231-5231-482a-a212-054921980312",
    "email": "user@example.com",
    "jti": "5a1984bc-21a4-4df1-bc4a-928190248102",
    "type": "access",
    "iss": "buyorwait",
    "aud": "buyorwait_api",
    "iat": 1726390800,
    "exp": 1726391700
  }
  ```

### 2.4 Token Lifecycle & Revocation
1. **Issuance**: On successful credential verification at `POST /api/v1/auth/login`.
2. **Validation**: Every authenticated request decodes signature, validates `exp`, `iss`, `aud`, `type == 'access'`, and queries `revoked_tokens` table.
3. **Revocation (Logout)**: User calls `POST /api/v1/auth/logout`. The token's unique `jti` and expiration timestamp are persisted to the PostgreSQL `revoked_tokens` table. Any subsequent request presenting this `jti` is immediately rejected with `401 Unauthorized` (`Token revoked`).
4. **Cleanup**: Expired revocation rows are pruned periodically where `expires_at < utc_now()`.

---

## 3. Authorization & Tenant Isolation

- **Boundary Enforcement**: Every authenticated endpoint resolves tenant identity exclusively from the validated JWT subject (`get_current_user`). No endpoint trusts client-supplied `user_id` route or query parameters.
- **Repository Isolation**: All database lookups filter explicitly on `tenant_id == current_user.id`.
- **Anti-Enumeration 404 Responses**: Attempting to read, update, or delete another user's account, statement import, or purchase decision returns `404 Not Found` (`RESOURCE_NOT_FOUND`) rather than `403 Forbidden`. Attackers cannot determine whether a foreign UUID exists.

---

## 4. Rate Limiting & Abuse Protection

Implemented via thread-safe sliding-window rate limiter in `backend/auth/rate_limiter.py` and middleware in `backend/api/middleware/rate_limit.py`.

### 4.1 Quota Matrix (Per 60-Second Rolling Window)
| Category | Routes Included | Limit | Bucket Key | Rationale |
|---|---|:---:|---|---|
| **Auth** | `/api/v1/auth/login`, `/api/v1/auth/register` | **5** | Client IP | Defends against credential stuffing and registration spam. |
| **Purchases** | `/api/v1/purchases/evaluate` | **30** | User ID / Token | Prevents CPU exhaustion from rapid 90-day Monte Carlo/stress simulations. |
| **Uploads** | `/api/v1/imports` | **10** | User ID / Token | Protects disk I/O and parsing resources. |
| **General** | All other `/api/v1/` routes | **120** | User ID / IP | Generous limit for standard dashboard reads. |

### 4.2 Brute-Force Temporary Lockout
- Failed login attempts are tracked per `(client_ip, email)`.
- If 5 consecutive failures occur within a 5-minute window, subsequent attempts are rejected with `429 Too Many Requests` (`AUTH_THROTTLED`) and a `Retry-After: 60` header.
- Successful login immediately resets the failure counter.
- Legitimate accounts are never permanently locked.

---

## 5. File Upload Security Controls

Statement uploads at `POST /api/v1/imports` pass 5 security verification gates:
1. **Size Enforcement**: Payload length checked before streaming. Files $> 10\text{ MB}$ rejected with RFC 7807 `413 Payload Too Large`.
2. **Extension Whitelist**: Only `.csv`, `.txt`, `.tsv` permitted. Executable extensions (`.exe`, `.sh`, `.bat`, `.dll`) rejected with `415 Unsupported Media Type`.
3. **Binary Signature Defense**: Magic byte headers inspected. Immediate rejection for Windows PE (`MZ`), Linux ELF (`ELF`), Mach-O, ZIP, RAR, GZIP, 7z, and PDF.
4. **Path Traversal Defense**: User-supplied filenames sanitized via `os.path.basename`, stripped of null bytes (` `) and directory separators (`/`, `\`), and scrubbed with alphanumeric regex `[^a-zA-Z0-9._-]`.
5. **Quarantine Isolation**: Uploads stored in dedicated tenant directories (`quarantine/<user_id>/<random_uuid>.raw`) with path boundary assertions preventing filesystem escape.

---

## 6. Secret Management & Environment Profiles

### 6.1 Configuration Modes
- `ENVIRONMENT=development`: Permissive development defaults for quick local iteration.
- `ENVIRONMENT=testing`: Fast in-memory SQLite and isolated test mocks.
- `ENVIRONMENT=production`: Strict security validation enforced on application boot:
  - Startup fails immediately if `JWT_SECRET_KEY` has length $< 32$ or contains `"insecure"` or `"dev"`.
  - Startup fails immediately if `CORS_ORIGINS` contains wildcard (`*`).
  - Strict HTTPS and HSTS required.

### 6.2 Secret Ingestion
- Real credentials must be injected via secure environment variables or vault mounts (e.g. AWS Secrets Manager, HashiCorp Vault, Kubernetes Secrets).
- No secrets exist in source code, commit history, test fixtures, or Docker image layers.
- `.env` and `*.db` are strictly ignored in `.gitignore`.

---

## 7. Security Headers & CORS Policy

All HTTP responses inject hardened security headers:
- `X-Content-Type-Options: nosniff` (prevents MIME-sniffing attacks)
- `X-Frame-Options: DENY` (clickjacking defense)
- `Strict-Transport-Security: max-age=31536000; includeSubDomains; preload` (enforces HTTPS)
- `Referrer-Policy: strict-origin-when-cross-origin` (prevents leaking query paths in referrers)
- `Permissions-Policy: geolocation=(), camera=(), microphone=()` (disables browser APIs)
- `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'` (hardened API policy)
- `Cache-Control: no-store, no-cache, must-revalidate, private` on sensitive routes (prevents browser/proxy caching of balances and transactions)

---

## 8. Audit Logging Policy

Security events are written to the immutable `audit_events` table in PostgreSQL:
- `user_registered`: User registration timestamp and metadata.
- `login_success`: Authenticated session establishment with client IP.
- `login_failed`: Authentication failure with IP and consecutive failure count.
- `logout`: Session termination and revoked `jti`.
- `cross_tenant_access_denied`: Attempted cross-tenant access.

**Zero-Knowledge Audit Invariant**: Passwords, password hashes, JWT secret keys, raw unencrypted account numbers, and statement payloads are NEVER included in audit logs.

---

## 9. Docker Runtime Hardening

The production container (`Dockerfile`) follows the principle of least privilege:
1. **Multi-Stage Build**: Compilation tools (`build-essential`, `libpq-dev`) discarded in builder stage; runner image contains only runtime libraries (`libpq5`).
2. **Non-Root Execution**: Runs under unprivileged user `appuser:appgroup` (UID/GID `10001`).
3. **Dropped Capabilities**: `cap_drop: ALL` and `no-new-privileges: true` configured in `docker-compose.yml`.
4. **Health Checking**: Uses lightweight `curl` health probes against `/api/v1/health` without root utilities.
