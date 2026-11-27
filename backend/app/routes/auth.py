"""Authentication endpoints.

Mounted at /api/auth WITHOUT a router-level auth dependency: `login` is public,
while `me` and token revocation enforce auth via the CurrentUser parameter.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.auth import CurrentUser, security
from app.auth_events import client_ip, record_auth_event
from app.database import DbSession
from app.models.api_token import ApiToken
from app.models.user import User
from app.rate_limit import limiter
from app.security import generate_token, hash_password, hash_token, verify_password
from app.token_scope import COACH, FULL

router = APIRouter()


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class LoginRequest(_CamelModel):
    username: str
    password: str
    device_name: str | None = Field(default=None)


class UserOut(_CamelModel):
    id: uuid.UUID
    username: str
    display_name: str
    role: str


class LoginResponse(_CamelModel):
    token: str
    token_id: uuid.UUID  # this session's token id — for revoke-on-logout
    user: UserOut


class TokenOut(_CamelModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    last_used_at: datetime | None
    last_user_agent: str | None
    expires_at: datetime | None
    # "full" or "coach" (app/token_scope.py).
    scope: str


class MeResponse(_CamelModel):
    user: UserOut
    tokens: list[TokenOut]


class ChangePasswordRequest(_CamelModel):
    current_password: str
    new_password: str = Field(min_length=8)


class ChangePasswordResponse(_CamelModel):
    # Other sessions signed out by the change (this one stays valid).
    revoked_tokens: int


class MintTokenRequest(_CamelModel):
    name: str
    expires_at: AwareDatetime | None = None
    # "coach" for a token that is going into an assistant: it can do what the
    # coach's tools do and nothing else (app/token_scope.py). The default is
    # what this endpoint has always made.
    scope: Literal["full", "coach"] = FULL

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not (1 <= len(v) <= 100):
            raise ValueError("name must be 1-100 characters")
        return v


class MintTokenResponse(_CamelModel):
    token: str  # shown exactly once, same rule as login
    token_id: uuid.UUID


@router.post("/login", response_model=LoginResponse)
@limiter.limit("5/minute")
def login(request: Request, body: LoginRequest, db: DbSession) -> LoginResponse:
    username = body.username.strip().lower()
    user = db.scalar(select(User).where(User.username == username))
    # One indistinguishable failure for unknown user / wrong password / disabled
    # login / inactive account — never reveal which.
    if (
        user is None
        or not user.is_active
        or user.password_hash is None
        or not verify_password(user.password_hash, body.password)
    ):
        record_auth_event(db, "login_failed", username=username, ip=client_ip(request), commit=True)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    raw = generate_token()
    token = ApiToken(user_id=user.id, token_hash=hash_token(raw), name=(body.device_name or "").strip()[:100])
    db.add(token)
    record_auth_event(
        db, "login_success", username=username, user_id=user.id, ip=client_ip(request),
        detail={"device": token.name} if token.name else None,
    )
    db.commit()
    db.refresh(token)
    return LoginResponse(token=raw, token_id=token.id, user=UserOut.model_validate(user))


# ── first-run setup ──
#
# A fresh install has no admin password, so the login form is dead on arrival.
# These two unauthenticated endpoints let the SPA detect that state and create
# the admin account in the browser; they hard-close the moment a passworded
# admin exists. Deliberately never 401 (the SPA wipes its token on any 401).


class SetupStatusResponse(_CamelModel):
    required: bool


class SetupRequest(_CamelModel):
    username: str = "admin"
    password: str = Field(min_length=8)
    display_name: str | None = None

    @field_validator("username")
    @classmethod
    def _normalize_username(cls, v: str) -> str:
        v = v.strip().lower()
        if not (1 <= len(v) <= 32) or any(c.isspace() for c in v):
            raise ValueError("username must be 1-32 characters with no whitespace")
        return v


_SETUP_LOCK_KEY = 0x4C6F6F70  # "Loop" — pg advisory lock serializing setup


def _setup_required(db: Session) -> bool:
    # True iff no admin has a password — active or not. A deactivated-but-
    # passworded admin must NOT reopen setup (that install has data; lockout
    # recovery is the CLI, not an open network endpoint).
    return db.scalar(select(User.id).where(User.role == "admin", User.password_hash.is_not(None)).limit(1)) is None


@router.get("/setup", response_model=SetupStatusResponse)
def setup_status(db: DbSession) -> SetupStatusResponse:
    return SetupStatusResponse(required=_setup_required(db))


@router.post("/setup", response_model=LoginResponse)
@limiter.limit("5/minute")
def setup(request: Request, body: SetupRequest, db: DbSession) -> LoginResponse:
    # The advisory xact lock (released on commit/rollback) serializes
    # concurrent attempts, so the check + create below can't double-run.
    db.execute(select(func.pg_advisory_xact_lock(_SETUP_LOCK_KEY)))
    if not _setup_required(db):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Setup has already been completed")

    display = (body.display_name or "").strip()
    user = db.scalar(select(User).where(User.username == body.username))
    if user is None:
        user = User(
            username=body.username,
            display_name=display or body.username,
            role="admin",
            password_hash=hash_password(body.password),
        )
        db.add(user)
        db.flush()  # assign user.id for the token + event rows
    elif user.password_hash is None:
        # Claim the seeded/bootstrap admin: set password, promote, reactivate.
        user.password_hash = hash_password(body.password)
        user.role = "admin"
        user.is_active = True
        if display:
            user.display_name = display
    else:
        # A passworded (non-admin) account with that name exists — setup must
        # not hijack it.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")

    raw = generate_token()
    token = ApiToken(user_id=user.id, token_hash=hash_token(raw), name="Web dashboard")
    db.add(token)
    record_auth_event(db, "setup_completed", username=user.username, user_id=user.id, ip=client_ip(request))
    db.commit()
    db.refresh(token)
    return LoginResponse(token=raw, token_id=token.id, user=UserOut.model_validate(user))


@router.get("/me", response_model=MeResponse)
def me(user: CurrentUser, db: DbSession) -> MeResponse:
    tokens = db.scalars(
        select(ApiToken).where(ApiToken.user_id == user.id).order_by(ApiToken.created_at)
    ).all()
    return MeResponse(user=UserOut.model_validate(user), tokens=[TokenOut.model_validate(t) for t in tokens])


@router.post("/password", response_model=ChangePasswordResponse)
def change_password(
    body: ChangePasswordRequest,
    user: CurrentUser,
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
) -> ChangePasswordResponse:
    # 400 (not 401) on a wrong current password — the SPA treats any 401 as
    # "token dead" and would log the whole session out.
    if user.password_hash is None or not verify_password(user.password_hash, body.current_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    user.password_hash = hash_password(body.new_password)
    result = db.execute(
        delete(ApiToken).where(
            ApiToken.user_id == user.id, ApiToken.token_hash != hash_token(credentials.credentials)
        )
    )
    record_auth_event(
        db, "password_changed", username=user.username, user_id=user.id, actor_user_id=user.id,
        detail={"revoked_tokens": result.rowcount},
    )
    db.commit()
    return ChangePasswordResponse(revoked_tokens=result.rowcount)


@router.post("/tokens", response_model=MintTokenResponse, status_code=status.HTTP_201_CREATED)
def mint_token(body: MintTokenRequest, user: CurrentUser, db: DbSession) -> MintTokenResponse:
    raw = generate_token()
    token = ApiToken(
        user_id=user.id, token_hash=hash_token(raw), name=body.name, expires_at=body.expires_at, scope=body.scope
    )
    db.add(token)
    record_auth_event(
        db, "token_created", username=user.username, user_id=user.id, actor_user_id=user.id,
        detail={"name": body.name, **({"scope": COACH} if body.scope == COACH else {})},
    )
    db.commit()
    db.refresh(token)
    return MintTokenResponse(token=raw, token_id=token.id)


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_token(token_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    token = db.get(ApiToken, token_id)
    if token is None or token.user_id != user.id:
        # 404 (not 403) so one user can't probe another's token ids.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")
    record_auth_event(
        db, "token_revoked", username=user.username, user_id=user.id, actor_user_id=user.id,
        detail={"name": token.name},
    )
    db.delete(token)
    db.commit()
