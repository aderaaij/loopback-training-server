"""Admin user-management endpoints (the dashboard Users screen).

Mirrors the `app.cli` verbs (list-users / create-user / set-password) plus
deactivate/reactivate. camelCase on the wire like the auth router. Every route
is guarded by the router-level admin dependency.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel
from sqlalchemy import delete, func, select

from app.auth import CurrentAdmin, get_current_admin
from app.database import DbSession
from app.models.api_token import ApiToken
from app.models.user import User
from app.security import hash_password

router = APIRouter(dependencies=[Depends(get_current_admin)])

_ROLES = ("user", "admin")


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class AdminUserOut(_CamelModel):
    id: uuid.UUID
    username: str
    display_name: str
    role: str
    is_active: bool
    token_count: int
    # Max last_used_at across the user's tokens; null = never used a token.
    last_seen_at: datetime | None


class CreateUserRequest(_CamelModel):
    username: str
    password: str = Field(min_length=8)
    display_name: str | None = None
    role: str = "user"

    @field_validator("username")
    @classmethod
    def _normalize_username(cls, v: str) -> str:
        v = v.strip().lower()
        if not (1 <= len(v) <= 32) or any(c.isspace() for c in v):
            raise ValueError("username must be 1-32 characters with no whitespace")
        return v

    @field_validator("role")
    @classmethod
    def _check_role(cls, v: str) -> str:
        if v not in _ROLES:
            raise ValueError(f"role must be one of {_ROLES}")
        return v


class ResetPasswordRequest(_CamelModel):
    password: str = Field(min_length=8)


class UpdateUserRequest(_CamelModel):
    is_active: bool | None = None


def _token_stats(db: DbSession, user_id: uuid.UUID) -> tuple[int, datetime | None]:
    return db.execute(
        select(func.count(ApiToken.id), func.max(ApiToken.last_used_at)).where(ApiToken.user_id == user_id)
    ).one()


def _to_out(user: User, token_count: int, last_seen_at: datetime | None) -> AdminUserOut:
    return AdminUserOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        is_active=user.is_active,
        token_count=token_count,
        last_seen_at=last_seen_at,
    )


def _get_user_or_404(db: DbSession, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.get("/users", response_model=list[AdminUserOut])
def list_users(db: DbSession) -> list[AdminUserOut]:
    rows = db.execute(
        select(User, func.count(ApiToken.id), func.max(ApiToken.last_used_at))
        .outerjoin(ApiToken, ApiToken.user_id == User.id)
        .group_by(User.id)
        .order_by(User.created_at)
    ).all()
    return [_to_out(user, count, seen) for user, count, seen in rows]


@router.post("/users", response_model=AdminUserOut, status_code=status.HTTP_201_CREATED)
def create_user(body: CreateUserRequest, db: DbSession) -> AdminUserOut:
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")
    user = User(
        username=body.username,
        display_name=(body.display_name or "").strip() or body.username,
        role=body.role,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _to_out(user, 0, None)


@router.post("/users/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(user_id: uuid.UUID, body: ResetPasswordRequest, db: DbSession) -> None:
    user = _get_user_or_404(db, user_id)
    user.password_hash = hash_password(body.password)
    db.commit()


@router.patch("/users/{user_id}", response_model=AdminUserOut)
def update_user(user_id: uuid.UUID, body: UpdateUserRequest, admin: CurrentAdmin, db: DbSession) -> AdminUserOut:
    user = _get_user_or_404(db, user_id)
    if body.is_active is not None:
        if not body.is_active:
            if user.id == admin.id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot deactivate your own account"
                )
            # The UI promises "devices stop authenticating immediately" — auth
            # already rejects inactive users, deleting the rows keeps /me tidy.
            db.execute(delete(ApiToken).where(ApiToken.user_id == user.id))
        user.is_active = body.is_active
    db.commit()
    count, seen = _token_stats(db, user.id)
    return _to_out(user, count, seen)
