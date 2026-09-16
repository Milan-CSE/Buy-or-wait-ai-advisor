# Security & Privacy Specification: Buy or Wait?

**Document Version**: 1.0.0  
**Phase**: Phase 1 — Production Architecture & Discovery  
**Classification**: Engineering Security Controls & Privacy Architecture

---

## 1. Authentication & Session Management

### 1.1 Credential Storage & Password Hashing
- **Algorithm**: Argon2id (`m=65536` [64 MiB memory], `t=3` iterations, `p=4` parallelism).
- **Enforcement**: Minimum 12 characters, requiring upper/lowercase, numbers, and symbols. Checked against HaveIBeenPwned top 100k breached passwords.
- **Salting**: Cryptographically random 16-byte salt per user generated via `os.urandom()`.

### 1.2 Token Architecture
- **Access Tokens**: Short-lived JSON Web Tokens (JWT) signed using asymmetric EdDSA (Ed25519) or RSA-256 (`RS256`).
  - Lifespan: **15 minutes**.
  - Claims: `sub` (User UUID), `iss` ("buyorwait-api"), `iat`, `exp`, `jti` (unique token ID).
- **Refresh Tokens**: Opaque 64-character high-entropy string stored as a SHA-256 hash in Redis/PostgreSQL.
  - Lifespan: **7 days** with sliding window renewal.
  - Revocation: Instant revocation upon logout, password reset, or suspicious IP divergence.
  - Blacklist: Redis Bloom filter or key expiry check for revoked `jti` tokens.

---

## 2. Authorization & Tenant Isolation

### 2.1 Threat Model: Cross-Tenant Financial Data Leakage
Financial transactions, bank statements, and purchase proposals must never be accessible across users.

### 2.2 Engineering Controls
1. **Explicit Scoped ORM Queries**: All repository queries must enforce user ownership at the data access layer:
   ```python
   # Mandatory pattern: user_id is injected from verified JWT claim, never client payload
   async def get_purchase(db: AsyncSession, purchase_id: UUID, current_user_id: UUID) -> Purchase:
       stmt = select(Purchase).where(Purchase.id == purchase_id, Purchase.user_id == current_user_id)
       res = await db.execute(stmt)
       if not res.scalar_one_or_none():
           raise NotFoundException("Purchase not found")
   ```
2. **PostgreSQL Row-Level Security (RLS)**:
   - Optional defense-in-depth enabled on `transactions`, `purchase_requests`, and `decisions`:
     `CREATE POLICY tenant_isolation ON transactions USING (user_id = current_setting('app.current_user_id')::uuid);`
3. **ID Design**: Public identifiers use UUIDv4 or KSUID to prevent ID enumeration/sequential scraping attacks.

---

## 3. Cryptography & Data Protection

### 3.1 Data in Transit
- **TLS**: Strict TLS 1.3 (TLS 1.2 fallback with ECDHE cipher suites only; RSA key exchange disabled).
- **HSTS**: `Strict-Transport-Security: max-age=63072000; includeSubDomains; preload`.
- **Certificate Management**: Automated certificate rotation via Let's Encrypt / AWS Certificate Manager.

### 3.2 Data at Rest
- **Database Volumes**: Full-disk encryption using AES-256 (AWS EBS KMS or LUKS).
- **Object Storage**: S3 Server-Side Encryption with Customer Managed KMS keys (SSE-KMS) with automatic yearly key rotation.
- **Sensitive Column Encryption**: Account identifiers and financial institution names encrypted at the application layer using AES-GCM-256 with keys managed outside the database.

---

## 4. Data Minimization & Privacy

1. **Account Number Masking**: The full bank account number is **never stored**. Statements are parsed to extract only the last 4 digits (`account_mask: "1024"`).
2. **PII Stripping**: Physical addresses, phone numbers, and national IDs parsed from statement headers are discarded immediately in memory prior to database insertion.
3. **Transaction Description Sanitization**: Raw merchant descriptions are sanitized to remove personally identifying memos (e.g., Zelle transfer comments containing personal phone numbers or names).

---

## 5. File Upload Security (Statement Ingestion)

Bank statement uploads (CSV/OFX) are a high-risk attack vector for Server-Side Request Forgery (SSRF), Denial of Service (Billion Laughs / Zip Bombs), and malware execution.

### 5.1 Upload Defense Pipeline
```
[Client File Upload]
        │
        ▼
1. File Size Verification (Max 10 MB strict limit in Nginx reverse proxy)
        │
        ▼
2. MIME & Magic Byte Validation (python-magic inspecting file header; reject executables)
        │
        ▼
3. Antivirus Scanning (ClamAV container scans uploaded buffer in memory)
        │
        ▼
4. Ephemeral Parsing Sandbox (Parsed in unprivileged worker; no shell execution)
        │
        ▼
5. S3 Encrypted Storage (Direct upload to private quarantine bucket with signed URLs)
```

### 5.2 CSV Injection (Formula Injection) Prevention
- In spreadsheet exports or user preview views, all string fields starting with `=`, `+`, `-`, `@`, or `\t` are prefixed with an apostrophe `'` to prevent formula execution when opened in Excel/Sheets.

---

## 6. Auditability & Tamper Evidence

1. **Append-Only Audit Log**: Every state modification (balance adjustment, category rule update, statement import, decision calculation) generates an immutable row in `audit_logs`.
2. **Payload Hash Chaining**: Decisions contain `raw_engine_payload` storing exact candidate inputs, state ledger, and P90 metrics. A SHA-256 hash of the inputs and outputs is stored for dispute resolution.
3. **Retention Policy**: Audit logs retained for 7 years in cold storage (S3 Glacier Vault with WORM compliance where required).

---

## 7. Data Subject Rights & Deletion (GDPR / CCPA)

### 7.1 Right to Erasure ("Forget Me")
When a user requests account deletion via `DELETE /api/v1/profile`:
1. **Database Cascade**:
   - `User`, `FinancialProfile`, `Account`, `Transaction`, `RecurringRule`, `PurchaseRequest`, `Decision`, `RiskAssessment` records deleted in a single transactional cascade.
2. **Storage Purge**:
   - Background worker deletes all statement files in `s3://buyorwait-statements/{user_id}/*`.
3. **Cache Invalidation**:
   - Flush all Redis keys prefixed with `user:{user_id}:*` and `idemp:{user_id}:*`.
4. **Tombstone Log**:
   - Record in audit log: `user_id=<hash>, event="user_deleted", timestamp=now()`. No PII retained.

---

## 8. Abuse Mitigation & Rate Limiting

- **Implementation**: Redis Token Bucket algorithm implemented via Redis Lua script.
- **Tiers**:
  - `POST /auth/login`: 5 requests / minute per IP (exponential backoff after 3 failed attempts).
  - `POST /purchases/evaluate`: 30 requests / minute per authenticated user (burst up to 10).
  - `POST /statements/upload`: 5 uploads / hour per user (prevent storage exhaustion).
  - Global API: 120 requests / minute per IP for unauthenticated routes.

---

## 9. Engineering Controls vs. Legal Compliance Boundary

> [!IMPORTANT]
> **Engineering vs Legal Disclaimer**: The controls specified in this document are technical security and privacy protections designed according to industry best practices (OWASP ASVS Level 2, SOC 2 Type II controls). They do **not** constitute legal compliance certifications. Legal counsel must independently review and approve customer terms of service, privacy policies, and regulatory compliance for Gramm-Leach-Bliley Act (GLBA), Fair Credit Reporting Act (FCRA), GDPR, CCPA, and regional banking guidelines.
