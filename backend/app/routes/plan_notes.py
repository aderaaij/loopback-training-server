import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import or_, select

from app.auth import CurrentUser
from app.database import DbSession
from app.models.plan import Plan
from app.models.plan_note import PlanNote
from app.models.user import User
from app.schemas.plan_note import PlanContext, PlanNoteCreate, PlanNoteRead, PlanNoteUpdate
from app.tenancy import get_owned

router = APIRouter()


def _resolve_active_plan(db: DbSession, user: User) -> Plan | None:
    q = (
        select(Plan)
        .where(Plan.user_id == user.id, Plan.status == "active")
        .order_by(Plan.created_at.desc())
    )
    return db.scalars(q).first()


def _not_expired_filter(now: datetime):
    return or_(PlanNote.expires_at.is_(None), PlanNote.expires_at > now)


@router.post("", response_model=PlanNoteRead, status_code=status.HTTP_201_CREATED)
def create_note(payload: PlanNoteCreate, db: DbSession, user: CurrentUser):
    if payload.plan_id is not None:
        get_owned(db, Plan, payload.plan_id, user)  # 404s if the plan isn't the caller's
    note = PlanNote(
        user_id=user.id,
        plan_id=payload.plan_id,
        kind=payload.kind,
        summary=payload.summary,
        body=payload.body,
        importance=payload.importance,
        conversation_id=payload.conversation_id,
        expires_at=payload.expires_at,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


@router.get("", response_model=list[PlanNoteRead])
def list_notes(
    db: DbSession,
    user: CurrentUser,
    plan_id: uuid.UUID | None = None,
    kind: str | None = None,
    conversation_id: str | None = None,
    since_days: int | None = None,
    include_expired: bool = False,
    limit: int = Query(default=50, le=200),
):
    q = select(PlanNote).where(PlanNote.user_id == user.id)

    if plan_id is not None:
        q = q.where(PlanNote.plan_id == plan_id)
    if kind:
        q = q.where(PlanNote.kind == kind)
    if conversation_id:
        q = q.where(PlanNote.conversation_id == conversation_id)
    if since_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        q = q.where(PlanNote.created_at >= cutoff)
    if not include_expired:
        q = q.where(_not_expired_filter(datetime.now(timezone.utc)))

    q = q.order_by(PlanNote.importance.desc(), PlanNote.created_at.desc()).limit(limit)
    return db.scalars(q).all()


@router.get("/context", response_model=PlanContext)
def get_context(
    db: DbSession,
    user: CurrentUser,
    plan_id: uuid.UUID | None = None,
    since_days: int = Query(default=60, ge=1, le=365),
    limit: int = Query(default=40, ge=1, le=200),
):
    """Aggregated continuity payload for LLM conversations.

    Returns the resolved plan plus recent non-expired notes ranked by
    importance then recency, plus a continuity hint string.
    """
    plan: Plan | None
    if plan_id is None:
        plan = _resolve_active_plan(db, user)
    else:
        plan = get_owned(db, Plan, plan_id, user)

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=since_days)

    note_q = (
        select(PlanNote)
        .where(PlanNote.user_id == user.id)
        .where(PlanNote.created_at >= cutoff)
        .where(_not_expired_filter(now))
    )
    if plan is not None:
        note_q = note_q.where(or_(PlanNote.plan_id == plan.id, PlanNote.plan_id.is_(None)))
    else:
        note_q = note_q.where(PlanNote.plan_id.is_(None))

    note_q = note_q.order_by(PlanNote.importance.desc(), PlanNote.created_at.desc()).limit(limit)
    notes = db.scalars(note_q).all()

    last_note_age_days: int | None = None
    if notes:
        latest = max(n.created_at for n in notes)
        last_note_age_days = (now - latest).days

    if last_note_age_days is None:
        hint = (
            "No recent notes. If the user shares any preference, decision, "
            "constraint, or life context that affects training during this "
            "conversation, call append_plan_note before the conversation ends."
        )
    elif last_note_age_days >= 7:
        hint = (
            f"Last note was {last_note_age_days} days ago. If anything plan-relevant "
            "comes up in this conversation, save it with append_plan_note — "
            "continuity has been thin."
        )
    else:
        hint = (
            "Continuity is fresh. Continue calling append_plan_note for new "
            "decisions, preferences, or life-context shifts as they emerge."
        )

    return PlanContext(
        plan=plan,
        notes=notes,
        last_note_age_days=last_note_age_days,
        continuity_hint=hint,
    )


@router.get("/{note_id}", response_model=PlanNoteRead)
def get_note(note_id: uuid.UUID, db: DbSession, user: CurrentUser):
    return get_owned(db, PlanNote, note_id, user)


@router.patch("/{note_id}", response_model=PlanNoteRead)
def update_note(note_id: uuid.UUID, payload: PlanNoteUpdate, db: DbSession, user: CurrentUser):
    note = get_owned(db, PlanNote, note_id, user)

    if payload.kind is not None:
        note.kind = payload.kind
    if payload.summary is not None:
        note.summary = payload.summary
    if payload.body is not None:
        note.body = payload.body
    if payload.importance is not None:
        note.importance = payload.importance
    if payload.expires_at is not None:
        note.expires_at = payload.expires_at

    db.commit()
    db.refresh(note)
    return note


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(note_id: uuid.UUID, db: DbSession, user: CurrentUser):
    note = get_owned(db, PlanNote, note_id, user)
    db.delete(note)
    db.commit()
