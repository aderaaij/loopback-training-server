"""Self-service endpoints operating on the token's own user.

Currently just data consent. camelCase on the wire like the other
identity-shaped routes (auth, admin), not the snake_case of the data routes.
"""

from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from sqlalchemy import func

from app.auth import CurrentUser
from app.auth_events import client_ip, record_auth_event
from app.data_consent import consent_state, normalize
from app.database import DbSession

router = APIRouter()


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class DataConsentUpdate(_CamelModel):
    # The complete set the athlete shares — a replacement, never a delta.
    domains: list[str] = Field(default_factory=list)


class DataConsentOut(_CamelModel):
    domains: list[str]
    # When the set last CHANGED (null = never reported).
    updated_at: datetime | None
    # When it was last REPORTED, changed or not (null = never reported). The
    # app pushes on every launch, so this is the "is the app still telling us"
    # signal; see app/data_consent.consent_state for why one stamp can't be both.
    reported_at: datetime | None


def _out(user) -> DataConsentOut:
    domains, updated_at, reported_at = consent_state(user)
    return DataConsentOut(domains=domains, updated_at=updated_at, reported_at=reported_at)


# Both spellings are registered on purpose. FastAPI's automatic
# trailing-slash redirect never fires in this app: the SPA catch-all in
# main.py matches `/{full_path:path}` first, so `/api/me/data-consent/` finds a
# GET-only route and a PUT to it comes back **405** — indistinguishable from
# "this endpoint doesn't exist", which is precisely the symptom the iOS app was
# reporting before this endpoint existed at all. A client that appends a slash
# would keep seeing the same 405 forever and have no way to tell why.
_PATHS = ("/data-consent", "/data-consent/")


@router.get(_PATHS[0], response_model=DataConsentOut)
@router.get(_PATHS[1], response_model=DataConsentOut, include_in_schema=False)
def get_data_consent(user: CurrentUser) -> DataConsentOut:
    """What this user currently shares with the coach.

    The MCP reads this to decide which tools to advertise; nothing else needs it.
    """
    return _out(user)


@router.put(_PATHS[0], response_model=DataConsentOut)
@router.put(_PATHS[1], response_model=DataConsentOut, include_in_schema=False)
def put_data_consent(
    body: DataConsentUpdate, request: Request, db: DbSession, user: CurrentUser
) -> DataConsentOut:
    """Replace the shared set.

    Idempotent, and hit far more often than it changes — the app reports on
    every launch. Unknown domain strings are stored rather than rejected: a
    newer app may report a domain this server hasn't learned, and a 400 there
    would break consent pushes for every user on an older server. `training` is
    always included; see app/data_consent.normalize.

    An audit row is written only when the set actually changes, so the trail
    stays readable — but `data_consent_reported_at` is stamped every time, so a
    user whose app has never reported is still distinguishable from one whose
    choice matches the default.
    """
    incoming = normalize(body.domains)
    changed = incoming != list(user.data_consent or [])

    now = func.now()
    user.data_consent = incoming
    user.data_consent_reported_at = now
    if changed or user.data_consent_updated_at is None:
        user.data_consent_updated_at = now
    if changed:
        record_auth_event(
            db,
            "data_consent_changed",
            username=user.username,
            user_id=user.id,
            ip=client_ip(request),
            detail={"domains": incoming},
        )

    db.commit()
    db.refresh(user)
    return _out(user)
