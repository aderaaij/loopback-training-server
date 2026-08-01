"""Admin endpoints (the dashboard Users + System screens).

User management mirrors the `app.cli` verbs (list-users / create-user /
set-password) plus deactivate/reactivate, per-user token inspection/revoke,
the auth-events activity feed, and system status (backups, DB size). camelCase
on the wire like the auth router. Every route is guarded by the router-level
admin dependency.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel
from sqlalchemy import delete, func, inspect, select, text

from app.auth import CurrentAdmin, get_current_admin
from app.auth_events import record_auth_event
from app.backup import BackupError, run_backup
from app.config import get_settings
from app.data_consent import DEFAULT_DOMAINS
from app.database import DbSession
from app.models.api_token import ApiToken
from app.models.auth_event import AuthEvent
from app.models.health_metrics import DailyHealthMetrics
from app.models.user import User
from app.models.workout import Workout
from app.security import hash_password
from app.version import __version__

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
    # Sync freshness — metadata only (timestamps, never content): when the last
    # workout ROW arrived (created_at, i.e. "is the iPhone still syncing"), and
    # the most recent day with health metrics.
    last_workout_sync_at: datetime | None = None
    last_health_date: date | None = None
    # Which data categories this user shares with the coach. Both stamps null =
    # the app has never reported, so the permissive default is in force —
    # the state worth seeing, since a failed push is otherwise silent.
    data_consent: list[str] = Field(default_factory=list)
    data_consent_updated_at: datetime | None = None
    data_consent_reported_at: datetime | None = None


class AdminTokenOut(_CamelModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    last_used_at: datetime | None
    last_user_agent: str | None
    expires_at: datetime | None


class AuthEventOut(_CamelModel):
    id: uuid.UUID
    event: str
    username: str | None
    actor_username: str | None
    ip: str | None
    detail: dict[str, Any] | None
    created_at: datetime


class BackupStatus(_CamelModel):
    file: str
    size_bytes: int
    completed_at: datetime


class SystemStatus(_CamelModel):
    app_version: str
    backup: BackupStatus | None
    backup_count: int
    db_size_bytes: int
    migration_head: str | None
    counts: dict[str, int]


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
        data_consent=list(user.data_consent or DEFAULT_DOMAINS),
        data_consent_updated_at=user.data_consent_updated_at,
        data_consent_reported_at=user.data_consent_reported_at,
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
    # Separate aggregates (not joins) — joining three one-to-many tables at
    # once would fan out the token stats.
    workout_sync = dict(
        db.execute(select(Workout.user_id, func.max(Workout.created_at)).group_by(Workout.user_id)).all()
    )
    health_date = dict(
        db.execute(
            select(DailyHealthMetrics.user_id, func.max(DailyHealthMetrics.date)).group_by(
                DailyHealthMetrics.user_id
            )
        ).all()
    )
    out = []
    for user, count, seen in rows:
        row = _to_out(user, count, seen)
        row.last_workout_sync_at = workout_sync.get(user.id)
        row.last_health_date = health_date.get(user.id)
        out.append(row)
    return out


@router.post("/users", response_model=AdminUserOut, status_code=status.HTTP_201_CREATED)
def create_user(body: CreateUserRequest, admin: CurrentAdmin, db: DbSession) -> AdminUserOut:
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")
    user = User(
        username=body.username,
        display_name=(body.display_name or "").strip() or body.username,
        role=body.role,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    db.flush()  # assign user.id so the event row can reference it
    record_auth_event(
        db, "user_created", username=user.username, user_id=user.id, actor_user_id=admin.id,
        detail={"role": user.role},
    )
    db.commit()
    db.refresh(user)
    return _to_out(user, 0, None)


@router.post("/users/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(user_id: uuid.UUID, body: ResetPasswordRequest, admin: CurrentAdmin, db: DbSession) -> None:
    user = _get_user_or_404(db, user_id)
    user.password_hash = hash_password(body.password)
    record_auth_event(db, "password_reset", username=user.username, user_id=user.id, actor_user_id=admin.id)
    db.commit()


@router.patch("/users/{user_id}", response_model=AdminUserOut)
def update_user(user_id: uuid.UUID, body: UpdateUserRequest, admin: CurrentAdmin, db: DbSession) -> AdminUserOut:
    user = _get_user_or_404(db, user_id)
    if body.is_active is not None and body.is_active != user.is_active:
        if not body.is_active:
            if user.id == admin.id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot deactivate your own account"
                )
            # The UI promises "devices stop authenticating immediately" — auth
            # already rejects inactive users, deleting the rows keeps /me tidy.
            db.execute(delete(ApiToken).where(ApiToken.user_id == user.id))
        record_auth_event(
            db,
            "user_deactivated" if not body.is_active else "user_reactivated",
            username=user.username,
            user_id=user.id,
            actor_user_id=admin.id,
        )
        user.is_active = body.is_active
    db.commit()
    count, seen = _token_stats(db, user.id)
    return _to_out(user, count, seen)


# ── per-user tokens ──


@router.get("/users/{user_id}/tokens", response_model=list[AdminTokenOut])
def list_user_tokens(user_id: uuid.UUID, db: DbSession) -> list[AdminTokenOut]:
    _get_user_or_404(db, user_id)
    tokens = db.scalars(
        select(ApiToken).where(ApiToken.user_id == user_id).order_by(ApiToken.created_at)
    ).all()
    return [AdminTokenOut.model_validate(t) for t in tokens]


@router.delete("/users/{user_id}/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_user_token(user_id: uuid.UUID, token_id: uuid.UUID, admin: CurrentAdmin, db: DbSession) -> None:
    user = _get_user_or_404(db, user_id)
    token = db.get(ApiToken, token_id)
    if token is None or token.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")
    record_auth_event(
        db, "token_revoked", username=user.username, user_id=user.id, actor_user_id=admin.id,
        detail={"name": token.name},
    )
    db.delete(token)
    db.commit()


# ── activity feed ──

_EVENT_RETENTION = timedelta(days=365)


@router.get("/events", response_model=list[AuthEventOut])
def list_events(db: DbSession, limit: int = 50) -> list[AuthEventOut]:
    limit = max(1, min(limit, 200))
    # Opportunistic retention: pruning here (not on the login hot path) keeps
    # the table bounded without a timer.
    db.execute(delete(AuthEvent).where(AuthEvent.created_at < datetime.now(timezone.utc) - _EVENT_RETENTION))
    db.commit()
    actor = select(User.username).where(User.id == AuthEvent.actor_user_id).scalar_subquery()
    rows = db.execute(
        select(AuthEvent, actor.label("actor_username")).order_by(AuthEvent.created_at.desc()).limit(limit)
    ).all()
    return [
        AuthEventOut(
            id=e.id,
            event=e.event,
            username=e.username,
            actor_username=actor_name,
            ip=e.ip,
            detail=e.detail,
            created_at=e.created_at,
        )
        for e, actor_name in rows
    ]


# ── system status ──


@router.get("/system", response_model=SystemStatus)
def system_status(db: DbSession) -> SystemStatus:
    backup: BackupStatus | None = None
    backup_count = 0
    backup_dir = Path(get_settings().backup_dir)
    if backup_dir.is_dir():
        dumps = sorted(backup_dir.glob("training-api-*.sql.gz"))
        backup_count = len(dumps)
        if dumps:
            latest = dumps[-1]  # timestamped names sort chronologically
            stat = latest.stat()
            backup = BackupStatus(
                file=latest.name,
                size_bytes=stat.st_size,
                completed_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            )
    db_size = db.scalar(text("SELECT pg_database_size(current_database())")) or 0
    # alembic_version is absent when the schema was built by create_all (tests);
    # check first so the raw query can't poison the session's transaction.
    migration_head = None
    if inspect(db.get_bind()).has_table("alembic_version"):
        migration_head = db.scalar(text("SELECT version_num FROM alembic_version"))
    counts = {
        "users": db.scalar(select(func.count(User.id))) or 0,
        "workouts": db.scalar(select(func.count(Workout.id))) or 0,
        "healthDays": db.scalar(select(func.count(DailyHealthMetrics.id))) or 0,
        "authEvents": db.scalar(select(func.count(AuthEvent.id))) or 0,
    }
    return SystemStatus(
        app_version=__version__,
        backup=backup,
        backup_count=backup_count,
        db_size_bytes=db_size,
        migration_head=migration_head,
        counts=counts,
    )


@router.post("/backup", response_model=BackupStatus)
def backup_now(admin: CurrentAdmin) -> BackupStatus:
    """The System screen's "Back up now". Sync route = runs in the threadpool,
    so a slow pg_dump doesn't block the event loop. Works even with the
    scheduler disabled — an explicit admin action."""
    try:
        path = run_backup(f"manual by {admin.username}")
    except BackupError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    stat = path.stat()
    return BackupStatus(
        file=path.name,
        size_bytes=stat.st_size,
        completed_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
    )
