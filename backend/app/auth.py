import time
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth_events import client_ip, record_auth_event
from app.database import DbSession, SessionLocal
from app.models.api_token import ApiToken
from app.models.user import User
from app.security import hash_token
from app.token_scope import COACH, coach_may

security = HTTPBearer()

# Don't write last_used_at on every request — only if it's this stale.
_TOUCH_INTERVAL = timedelta(minutes=5)

# A stranded device (revoked/expired token, deactivated account) retries in
# the background, so one dead token can 401 every few minutes for days. Audit
# at most one token_rejected event per key per window — the key is the token
# for expired/inactive (one stranded device = one clean signal) and the IP for
# unknown tokens (a scanner rotating garbage tokens can't mint a row per
# attempt). In-process state, same trade-off as the login rate-limit throttle
# in main.py.
_REJECT_EVENT_WINDOW_S = 6 * 3600.0
_reject_event_last: dict[str, float] = {}


def _record_rejection(
    db: Session,
    request: Request,
    *,
    reason: str,
    key: str,
    username: str | None = None,
    user_id: Any = None,
    detail: dict[str, Any] | None = None,
) -> None:
    now = time.monotonic()
    last = _reject_event_last.get(key)
    if last is not None and now - last < _REJECT_EVENT_WINDOW_S:
        return
    if len(_reject_event_last) > 1024:  # bound the map under a many-key flood
        _reject_event_last.clear()
    _reject_event_last[key] = now
    # commit=True: the 401 path writes nothing else (same as login_failed).
    record_auth_event(
        db, "token_rejected", username=username, user_id=user_id, ip=client_ip(request),
        detail={"reason": reason, **(detail or {})}, commit=True,
    )


def _touch_last_used(
    token_id,
    last_used_at: datetime | None,
    now: datetime,
    user_agent: str | None,
    prev_user_agent: str | None,
) -> None:
    # A changed User-Agent (app updated, different client) always writes —
    # that transition is the version-handshake signal and it's rare.
    if (
        last_used_at is not None
        and now - last_used_at < _TOUCH_INTERVAL
        and user_agent == prev_user_agent
    ):
        return
    # Separate session so this bookkeeping write never entangles with the
    # request's own transaction (which may commit or roll back independently).
    with SessionLocal() as s:
        s.execute(
            update(ApiToken)
            .where(ApiToken.id == token_id)
            .values(last_used_at=now, last_user_agent=user_agent)
        )
        s.commit()


def get_current_user(
    request: Request,
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
) -> User:
    token_hash = hash_token(credentials.credentials)
    token = db.scalar(select(ApiToken).where(ApiToken.token_hash == token_hash))
    if token is None:
        # Revoked or never existed — no row to attribute. The hash suffix lets
        # the feed tell one dead token repeating from many different ones.
        _record_rejection(
            db, request, reason="unknown", key=f"ip:{client_ip(request)}",
            detail={"token_hint": token_hash[-6:]},
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked token")

    now = datetime.now(timezone.utc)
    if token.expires_at is not None and token.expires_at < now:
        _record_rejection(
            db, request, reason="expired", key=f"token:{token.id}",
            username=token.user.username, user_id=token.user_id,
            detail={"name": token.name},
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")

    user = token.user
    if not user.is_active:
        _record_rejection(
            db, request, reason="inactive", key=f"token:{token.id}",
            username=user.username, user_id=user.id,
            detail={"name": token.name},
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User is inactive")

    if token.scope == COACH:
        # The route's own path (`/api/plans/{plan_id}`), which FastAPI records
        # when it matches the request; the caller has no say in it.
        route = getattr(request.scope.get("route"), "path", None)
        if not coach_may(request.method, route):
            # A coach token asking for something no coach tool asks for is
            # either a client of the athlete's own pointed at the wrong token
            # or someone trying out a token that leaked. Worth one line in the
            # feed either way; the status is 403, since the token itself is
            # fine and a 401 would send an assistant off to sign in again.
            _record_rejection(
                db, request, reason="scope", key=f"scope:{token.id}",
                username=user.username, user_id=user.id,
                detail={"name": token.name, "method": request.method, "path": route or request.url.path[:200]},
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This token is for the coach only and cannot be used for this request.",
            )
    # For app/data_consent.py: a coach token is consent-scoped whatever
    # headers the request carries.
    request.state.token_scope = token.scope

    ua = (request.headers.get("user-agent") or "").strip()[:300] or None
    _touch_last_used(token.id, token.last_used_at, now, ua, token.last_user_agent)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def token_is_live(raw_token: str) -> bool:
    """Whether `get_current_user` would accept this token right now.

    For the coach endpoint's door (app/mcp_mount.py), which needs the answer
    before any route runs. It only looks: no last-used stamp and no audit
    event, because the API calls the coach makes with the token do both.
    """
    with SessionLocal() as db:
        row = db.execute(
            select(ApiToken.expires_at, User.is_active)
            .join(User, ApiToken.user_id == User.id)
            .where(ApiToken.token_hash == hash_token(raw_token))
        ).first()
    if row is None or not row.is_active:
        return False
    return row.expires_at is None or row.expires_at >= datetime.now(timezone.utc)


def get_current_admin(user: CurrentUser) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


CurrentAdmin = Annotated[User, Depends(get_current_admin)]
