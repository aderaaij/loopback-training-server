from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, update

from app.database import DbSession, SessionLocal
from app.models.api_token import ApiToken
from app.models.user import User
from app.security import hash_token

security = HTTPBearer()

# Don't write last_used_at on every request — only if it's this stale.
_TOUCH_INTERVAL = timedelta(minutes=5)


def _touch_last_used(token_id, last_used_at: datetime | None, now: datetime) -> None:
    if last_used_at is not None and now - last_used_at < _TOUCH_INTERVAL:
        return
    # Separate session so this bookkeeping write never entangles with the
    # request's own transaction (which may commit or roll back independently).
    with SessionLocal() as s:
        s.execute(update(ApiToken).where(ApiToken.id == token_id).values(last_used_at=now))
        s.commit()


def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
) -> User:
    token = db.scalar(select(ApiToken).where(ApiToken.token_hash == hash_token(credentials.credentials)))
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked token")

    now = datetime.now(timezone.utc)
    if token.expires_at is not None and token.expires_at < now:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")

    user = token.user
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User is inactive")

    _touch_last_used(token.id, token.last_used_at, now)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_current_admin(user: CurrentUser) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


CurrentAdmin = Annotated[User, Depends(get_current_admin)]
