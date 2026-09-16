# Buy or Wait? — Production Persistence Layer Specification

## 1. Architectural Boundaries

The persistence layer forms the infrastructure foundation of the Buy or Wait? backend, isolating the database from the pure financial decision domain.

### Clean Layering
```
┌────────────────────────────────────────────────────────┐
│                   API / FastAPI Layer                  │
└───────────────────────────┬────────────────────────────┘
                            │
┌───────────────────────────▼────────────────────────────┐
│                  Application Services                  │
│       (Orchestrates persistence and domain engine)      │
└──────────────┬──────────────────────────┬──────────────┘
               │                          │
┌──────────────▼─────────────┐   ┌────────▼──────────────┐
│     Repositories Layer     │   │   buyorwait_engine    │
│  (SQLAlchemy 2.0 + Models) │   │ (Pure Domain Library) │
└──────────────┬─────────────┘   └───────────────────────┘
               │ Mappers
┌──────────────▼─────────────┐
│  Mappers (DTO Translation) │
└────────────────────────────┘
```

### Decoupling Rules
1. **Zero Database Imports in Engine**: `buyorwait_engine` contains no SQLAlchemy models, sessions, or queries.
2. **Explicit DTO Translation**: Persistence models never bleed into domain decision logic. `backend/database/mappers/` translates DB models to and from frozen domain dataclasses (`FinancialProfileInput`, `CashflowEventInput`, `PurchaseProposal`, `DecisionResult`).
3. **Dependency Inversion**: High-level application services depend on repository abstractions; domain modules depend only on standard library types (`Decimal`, `datetime.date`).

---

## 2. Repository Interfaces & Query Patterns

All user-owned entity repositories inherit from `TenantScopedRepository[T]`, enforcing automatic tenant boundary checks:

```python
class TenantScopedRepository(Generic[T]):
    def __init__(self, session: Session, user_id: uuid.UUID, model_cls: type[T]):
        self.session = session
        self.user_id = user_id
        self.model_cls = model_cls

    def get_by_id(self, entity_id: uuid.UUID) -> Optional[T]:
        stmt = select(self.model_cls).where(
            self.model_cls.id == entity_id,
            self.model_cls.user_id == self.user_id,
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list(self, limit: int = 100, offset: int = 0) -> Sequence[T]:
        stmt = (
            select(self.model_cls)
            .where(self.model_cls.user_id == self.user_id)
            .limit(limit)
            .offset(offset)
        )
        return self.session.execute(stmt).scalars().all()
```

### Specialized Query Operations
- **`TransactionRepository.get_events_for_period(start_date, end_date)`**: Fetches transactions in a chronological window scoped to `user_id` using the compound index `(user_id, transaction_date)`.
- **`TransactionRepository.find_by_hash(hash_str)`**: Performs O(1) deduplication lookups during statement uploads.
- **`DecisionRepository.save_decision(...)`**: Enforces append-only storage for immutable decision audits. Mutations on existing decisions are strictly prohibited.

---

## 3. Tenant Isolation Enforcement

1. **Composite Database Indexing**: Tenant isolation is supported at the storage layer via compound indexes prefixed by `user_id`.
2. **Repository-Level Ownership Verification**: When mutating or deleting an entity (`update()`, `delete()`), the repository verifies that `entity.user_id == self.user_id`. Any attempt to modify another tenant's entity raises `TenantAccessError`.
3. **Cascade Deletes**: When a `User` account is deleted, foreign keys configured with `ON DELETE CASCADE` automatically and atomically purge profiles, accounts, transactions, purchase proposals, and decision records.

---

## 4. Monetary Representation & Rounding Safety

To prevent floating-point inaccuracies, penny-drop errors, or cumulative rounding drift:
- All monetary columns in PostgreSQL are typed as `NUMERIC(18, 4)`.
- SQLAlchemy models configure `Numeric(18, 4, asdecimal=True)`, ensuring values are loaded and persisted strictly as Python `decimal.Decimal` objects.
- All domain DTOs (`PurchaseProposal`, `DecisionResult`, etc.) enforce `Decimal` inputs and reject IEEE 754 floating-point values during instantiation.

---

## 5. Migration Workflow with Alembic

Alembic manages all schema evolutions.

### Directory Layout
```
backend/alembic/
├── alembic.ini
├── env.py
├── script.py.mako
└── versions/
    └── 001_initial_schema.py
```

### Key Migration Commands
To inspect current migration status:
```bash
alembic -c backend/alembic.ini current
```

To run all pending migrations up to latest:
```bash
alembic -c backend/alembic.ini upgrade head
```

To roll back the previous migration:
```bash
alembic -c backend/alembic.ini downgrade -1
```

To generate a new autodetected migration revision:
```bash
alembic -c backend/alembic.ini revision --autogenerate -m "describe_change"
```

---

## 6. Running with Local PostgreSQL (Docker)

A production-ready PostgreSQL 16 container definition is provided in `docker-compose.yml`:

```bash
# Start PostgreSQL container in background
docker compose up -d postgres

# Run database migrations
alembic -c backend/alembic.ini upgrade head

# Stop database container
docker compose down
```

Environment variables are managed via `.env` (configured from `.env.example`):
```env
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=buyorwait_db
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/buyorwait_db
```

---

## 7. Testing Strategy

The persistence test suite (`backend/tests/`) guarantees correctness across:
1. **`test_migrations.py`**: Executes full migration upgrade to `head` and rollback to `base`.
2. **`test_crud_lifecycle.py`**: Validates create, read, update, and soft/hard deletion across all entities.
3. **`test_tenant_isolation.py`**: Proves that User A cannot read, modify, or delete entities belonging to User B, raising `TenantAccessError`.
4. **`test_constraints_and_invariants.py`**: Verifies unique email enforcement, 1:1 profile constraints, and atomic transaction rollback.
5. **`test_money_representation.py`**: Verifies exact 4-decimal-place preservation without float casting.
6. **`test_engine_persistence_loop.py`**: Full roundtrip integration from database entities $\rightarrow$ DTO mappers $\rightarrow$ `buyorwait_engine` evaluation $\rightarrow$ DB persistence.
