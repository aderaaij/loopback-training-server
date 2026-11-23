"""Setbacks: an illness or injury, from its first day to the day it is over.

camelCase on the wire. Dates are the athlete's local calendar days.

Shared with the coach under the `recovery` consent domain: a consent-scoped
caller (the MCP) gets a 403 when the athlete does not share it, and the plan
context leaves setbacks out. The app and dashboard are never filtered.
"""

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth import CurrentUser
from app.data_consent import RECOVERY, CurrentConsent
from app.database import DbSession
from app.models.health_metrics import DailyHealthMetrics
from app.models.setback import Setback, SetbackCheckin
from app.schemas.setback import CheckinUpsert, SetbackCreate, SetbackOut, SetbackUpdate
from app.setback_recovery import assess_recovery, baseline_window
from app.tenancy import get_owned


def _require_shared(consent: CurrentConsent) -> None:
    consent.require(RECOVERY)


router = APIRouter(dependencies=[Depends(_require_shared)])

# How long a finished setback stays in the plan context.
RECENT_DAYS = 21


def _out(db: Session, user, setback: Setback, today: date | None = None) -> SetbackOut:
    """The setback as sent, with a recovery read while it is still open."""
    today = today or datetime.now(timezone.utc).date()
    recovery = None
    if setback.end_date is None:
        first, _ = baseline_window(setback.start_date)
        rows = db.scalars(
            select(DailyHealthMetrics).where(
                DailyHealthMetrics.user_id == user.id,
                DailyHealthMetrics.date >= first,
            )
        ).all() if setback.kind == "illness" else []
        recovery = assess_recovery(setback.kind, setback.start_date, setback.checkins, rows, today)
    return SetbackOut.of(setback, today, recovery)


def _same_open_setback(db: Session, user, kind: str, body_part: str | None, skip: uuid.UUID | None = None):
    """An open setback this one would duplicate: the same kind, and for an
    injury the same body part. Two injuries can be open at once; two colds
    cannot."""
    q = select(Setback).where(Setback.user_id == user.id, Setback.kind == kind, Setback.end_date.is_(None))
    if skip is not None:
        q = q.where(Setback.id != skip)
    for other in db.scalars(q):
        if kind == "illness" or (other.body_part or "").lower() == (body_part or "").lower():
            return other
    return None


def _conflict(other: Setback) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            f"There is already an open {other.kind} since {other.start_date.isoformat()} "
            f"(id {other.id}). Update that one, or close it first."
        ),
    )


@router.get("", response_model=list[SetbackOut])
def list_setbacks(
    db: DbSession,
    user: CurrentUser,
    active: bool | None = Query(default=None, description="true: only open ones; false: only finished ones"),
    since: date | None = Query(default=None, description="Only setbacks still going on or after this day"),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Setbacks, open ones first, then the most recently started."""
    q = select(Setback).where(Setback.user_id == user.id)
    if active is True:
        q = q.where(Setback.end_date.is_(None))
    elif active is False:
        q = q.where(Setback.end_date.is_not(None))
    if since is not None:
        q = q.where(or_(Setback.end_date.is_(None), Setback.end_date >= since))
    q = q.order_by(Setback.end_date.is_not(None), Setback.start_date.desc()).limit(limit)
    return [_out(db, user, s) for s in db.scalars(q)]


@router.post("", response_model=SetbackOut, status_code=status.HTTP_201_CREATED)
def create_setback(payload: SetbackCreate, response: Response, db: DbSession, user: CurrentUser):
    """Log a setback. With an `id` the call is idempotent: sending the same
    id again updates that row and answers 200."""
    existing = db.get(Setback, payload.id) if payload.id is not None else None
    if existing is not None and existing.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="That id is already in use")

    if payload.end_date is None:
        other = _same_open_setback(db, user, payload.kind, payload.body_part, skip=payload.id)
        if other is not None:
            raise _conflict(other)

    values = payload.model_dump(exclude={"id"})
    if existing is not None:
        for key, value in values.items():
            setattr(existing, key, value)
        setback = existing
        response.status_code = status.HTTP_200_OK
    else:
        setback = Setback(user_id=user.id, **values)
        if payload.id is not None:
            setback.id = payload.id
        db.add(setback)
    db.commit()
    db.refresh(setback)
    return _out(db, user, setback)


@router.get("/{setback_id}", response_model=SetbackOut)
def get_setback(setback_id: uuid.UUID, db: DbSession, user: CurrentUser):
    return _out(db, user, get_owned(db, Setback, setback_id, user))


@router.patch("/{setback_id}", response_model=SetbackOut)
def update_setback(setback_id: uuid.UUID, payload: SetbackUpdate, db: DbSession, user: CurrentUser):
    setback = get_owned(db, Setback, setback_id, user)
    fields = payload.model_fields_set

    for required in ("kind", "severity", "start_date"):
        if required in fields and getattr(payload, required) is None:
            raise HTTPException(status_code=422, detail=f"{required} cannot be null")
    for name in ("kind", "severity", "start_date", "end_date", "body_part", "note"):
        if name in fields:
            setattr(setback, name, getattr(payload, name))

    if setback.end_date is not None and setback.end_date < setback.start_date:
        raise HTTPException(status_code=422, detail="endDate must not be before startDate")
    if setback.end_date is None and fields & {"end_date", "kind", "body_part"}:
        other = _same_open_setback(db, user, setback.kind, setback.body_part, skip=setback.id)
        if other is not None:
            raise _conflict(other)

    db.commit()
    db.refresh(setback)
    return _out(db, user, setback)


@router.delete("/{setback_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_setback(setback_id: uuid.UUID, db: DbSession, user: CurrentUser):
    setback = get_owned(db, Setback, setback_id, user)
    db.delete(setback)
    db.commit()


@router.put("/{setback_id}/checkins/{day}", response_model=SetbackOut)
def put_checkin(setback_id: uuid.UUID, day: date, payload: CheckinUpsert, db: DbSession, user: CurrentUser):
    """Record how the athlete felt on one day. One entry per day; sending the
    day again replaces it."""
    setback = get_owned(db, Setback, setback_id, user)
    if day < setback.start_date:
        raise HTTPException(status_code=422, detail="That day is before the setback started")

    checkin = next((c for c in setback.checkins if c.date == day), None)
    if checkin is None:
        setback.checkins.append(SetbackCheckin(date=day, status=payload.status, note=payload.note))
    else:
        checkin.status = payload.status
        # A status tapped in the app carries no note; keep the one the coach
        # wrote for that day unless this call names one.
        if "note" in payload.model_fields_set:
            checkin.note = payload.note
    db.commit()
    db.refresh(setback)
    return _out(db, user, setback)


@router.delete("/{setback_id}/checkins/{day}", response_model=SetbackOut)
def delete_checkin(setback_id: uuid.UUID, day: date, db: DbSession, user: CurrentUser):
    setback = get_owned(db, Setback, setback_id, user)
    setback.checkins[:] = [c for c in setback.checkins if c.date != day]
    db.commit()
    db.refresh(setback)
    return _out(db, user, setback)


# ── plan context ────────────────────────────────────────────────────────────


def context_setbacks(db: Session, user, today: date | None = None) -> list[SetbackOut]:
    """What the coach should know at the start of a conversation: every open
    setback, plus the ones that ended in the last few weeks."""
    today = today or datetime.now(timezone.utc).date()
    rows = db.scalars(
        select(Setback)
        .where(
            Setback.user_id == user.id,
            or_(Setback.end_date.is_(None), Setback.end_date >= today - timedelta(days=RECENT_DAYS)),
        )
        .order_by(Setback.end_date.is_not(None), Setback.start_date.desc())
    ).all()
    return [_out(db, user, s, today) for s in rows]


def _describe(s: SetbackOut) -> str:
    what = s.kind if not s.body_part else f"{s.kind} ({s.body_part})"
    return f"{s.severity} {what}"


def setback_hint(setbacks: list[SetbackOut]) -> str:
    """One paragraph telling the coach what to do about the setbacks above."""
    open_ones = [s for s in setbacks if s.active]
    recent = [s for s in setbacks if not s.active]
    parts: list[str] = []

    for s in open_ones:
        line = f"The athlete has an open {_describe(s)} since {s.start_date.isoformat()} (day {s.days})."
        if s.checkins:
            last = s.checkins[-1]
            line += f" Last status: '{last.status}' on {last.date.isoformat()}."
        else:
            line += " No daily status logged yet."
        parts.append(line)
        if s.recovery is not None and s.recovery.status == "looks_recovered":
            parts.append(
                f"Going by the recent data it looks over ({s.recovery.summary}) Tell the athlete what you "
                "see and ask whether they feel recovered; close it only if they say so."
            )
        elif s.recovery is not None and s.recovery.status == "not_yet":
            parts.append(f"Recovery check: {s.recovery.summary}")
    if open_ones:
        parts.append(
            "Acknowledge it before anything else and ask how they feel today; record the answer "
            "with log_setback_status. Do not schedule or encourage quality sessions or long runs "
            "while a setback is open. Read the return-to-running part of the coaching playbook "
            "before changing the plan, and propose changes rather than making them unasked. "
            "When the athlete says they are recovered, close it with update_setback (end_date)."
        )

    for s in recent:
        parts.append(
            f"Recovered from a {_describe(s)}: {s.start_date.isoformat()} to "
            f"{s.end_date.isoformat()} ({s.days} days)."
        )
    if recent and not open_ones:
        parts.append(
            "Check that the plan since then builds back gradually (playbook: return to running) "
            "and compare the first runs back with the ones before it."
        )
    return " ".join(parts)
