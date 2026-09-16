"""
backend/database/repositories/user_repository.py

Repository for managing tenant identity accounts and password credentials.
"""
from __future__ import annotations
import uuid
from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database.models.user import User


class UserRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        email: str,
        full_name: str = "",
        status: str = "active",
        password_hash: Optional[str] = None,
    ) -> User:
        user = User(
            email=email.strip().lower(),
            full_name=full_name,
            status=status,
            password_hash=password_hash,
        )
        self.session.add(user)
        return user

    def get_by_id(self, user_id: uuid.UUID) -> Optional[User]:
        return self.session.get(User, user_id)

    def get_by_email(self, email: str) -> Optional[User]:
        stmt = select(User).where(User.email == email.strip().lower())
        return self.session.execute(stmt).scalar_one_or_none()

    def update_password(self, user_id: uuid.UUID, password_hash: str) -> bool:
        user = self.get_by_id(user_id)
        if user:
            user.password_hash = password_hash
            return True
        return False

    def delete(self, user_id: uuid.UUID) -> bool:
        user = self.get_by_id(user_id)
        if user:
            self.session.delete(user)
            return True
        return False
