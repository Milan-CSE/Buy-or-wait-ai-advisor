"""
backend/database/repositories/revoked_token_repository.py

Repository for revoked token blacklist queries and management.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.database.models.revoked_token import RevokedToken


class RevokedTokenRepository:
    def __init__(self, session: Session):
        self.session = session

    def is_revoked(self, jti: str) -> bool:
        stmt = select(RevokedToken.jti).where(RevokedToken.jti == jti)
        return self.session.execute(stmt).scalar_one_or_none() is not None

    def revoke(self, jti: str, user_id: uuid.UUID, expires_at: datetime) -> RevokedToken:
        revoked = RevokedToken(
            jti=jti,
            user_id=user_id,
            expires_at=expires_at,
        )
        self.session.add(revoked)
        return revoked

    def prune_expired(self, now: Optional[datetime] = None) -> int:
        if now is None:
            now = datetime.now(timezone.utc)
        stmt = delete(RevokedToken).where(RevokedToken.expires_at < now)
        res = self.session.execute(stmt)
        return res.rowcount or 0
