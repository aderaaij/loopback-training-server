import uuid
from datetime import datetime, time, timezone

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.auth import CurrentUser
from app.database import DbSession
from app.models.plan import Plan
from app.models.queue import WorkoutQueue
from app.models.user import User
from app.schedule_utils import resolve_sessions
from app.schemas.plan import (
    PlanCreate,
    PlanRead,
    PlanSchedule,
    PlanScheduleResponse,
    PlanUpdate,
    ScheduledSession,
)
from app.schemas.queue import QueueItemRead
from app.tenancy import get_owned

router = APIRouter()


def _runs_by_date(db: DbSession, user: User, dates: list) -> dict:
    """Map each calendar date in the range to the titles of this user's queued
    workouts (Apple Watch compositions) scheduled that day — the things a
    strength session could collide with."""
    if not dates:
        return {}
    lo = datetime.combine(min(dates), time.min, tzinfo=timezone.utc)
    hi = datetime.combine(max(dates), time.max, tzinfo=timezone.utc)
    rows = db.scalars(
        select(WorkoutQueue).where(
            WorkoutQueue.user_id == user.id,
            WorkoutQueue.scheduled_date.is_not(None),
            WorkoutQueue.scheduled_date >= lo,
            WorkoutQueue.scheduled_date <= hi,
        )
    ).all()
    out: dict = {}
    for r in rows:
        out.setdefault(r.scheduled_date.date(), []).append(r.title)
    return out


def _build_schedule_response(db: DbSession, user: User, plan: Plan) -> PlanScheduleResponse:
    schedule = (plan.metadata_ or {}).get("schedule")
    raw_sessions = resolve_sessions(schedule)
    runs = _runs_by_date(db, user, [s["date"] for s in raw_sessions])

    sessions: list[ScheduledSession] = []
    warnings: list[str] = []
    for s in raw_sessions:
        conflict_titles = runs.get(s["date"], [])
        sessions.append(ScheduledSession(
            date=s["date"],
            weekday=s["weekday"],
            title=s["title"],
            routine_id=s["routineId"],
            conflict=bool(conflict_titles),
            conflicts_with=conflict_titles,
        ))
        if conflict_titles:
            warnings.append(
                f"{s['date'].isoformat()} '{s['title']}' overlaps scheduled run(s): "
                f"{', '.join(conflict_titles)}"
            )

    return PlanScheduleResponse(
        plan_id=plan.id,
        schedule=PlanSchedule.model_validate(schedule) if schedule else None,
        sessions=sessions,
        warnings=warnings,
    )


@router.post("", response_model=PlanRead, status_code=status.HTTP_201_CREATED)
def create_plan(payload: PlanCreate, db: DbSession, user: CurrentUser):
    plan = Plan(
        user_id=user.id,
        name=payload.name,
        activity_type=payload.activity_type,
        status=payload.status,
        start_date=payload.start_date,
        end_date=payload.end_date,
        description=payload.description,
        metadata_=payload.metadata,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


@router.get("", response_model=list[PlanRead])
def list_plans(
    db: DbSession,
    user: CurrentUser,
    plan_status: str | None = Query(default=None, alias="status"),
    activity_type: str | None = None,
):
    q = select(Plan).where(Plan.user_id == user.id).order_by(Plan.created_at.desc())

    if plan_status:
        q = q.where(Plan.status == plan_status)
    if activity_type:
        q = q.where(Plan.activity_type == activity_type)

    return db.scalars(q).all()


@router.get("/{plan_id}", response_model=PlanRead)
def get_plan(plan_id: uuid.UUID, db: DbSession, user: CurrentUser):
    return get_owned(db, Plan, plan_id, user)


@router.patch("/{plan_id}", response_model=PlanRead)
def update_plan(plan_id: uuid.UUID, payload: PlanUpdate, db: DbSession, user: CurrentUser):
    plan = get_owned(db, Plan, plan_id, user)

    if payload.name is not None:
        plan.name = payload.name
    if payload.activity_type is not None:
        plan.activity_type = payload.activity_type
    if payload.status is not None:
        plan.status = payload.status
    if payload.start_date is not None:
        plan.start_date = payload.start_date
    if payload.end_date is not None:
        plan.end_date = payload.end_date
    if payload.description is not None:
        plan.description = payload.description
    if payload.metadata is not None:
        plan.metadata_ = payload.metadata

    db.commit()
    db.refresh(plan)
    return plan


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_plan(plan_id: uuid.UUID, db: DbSession, user: CurrentUser):
    plan = get_owned(db, Plan, plan_id, user)
    db.delete(plan)
    db.commit()


@router.get("/{plan_id}/workouts", response_model=list[QueueItemRead])
def get_plan_workouts(plan_id: uuid.UUID, db: DbSession, user: CurrentUser):
    get_owned(db, Plan, plan_id, user)  # 404s if the plan isn't the caller's

    q = (
        select(WorkoutQueue)
        .where(WorkoutQueue.user_id == user.id, WorkoutQueue.plan_id == plan_id)
        .order_by(WorkoutQueue.created_at)
    )
    return db.scalars(q).all()


@router.get("/{plan_id}/schedule", response_model=PlanScheduleResponse)
def get_plan_schedule(plan_id: uuid.UUID, db: DbSession, user: CurrentUser):
    """Return the plan's recurring schedule expanded into concrete dated
    sessions, each flagged where it collides with a queued run."""
    plan = get_owned(db, Plan, plan_id, user)
    return _build_schedule_response(db, user, plan)


@router.put("/{plan_id}/schedule", response_model=PlanScheduleResponse)
def set_plan_schedule(plan_id: uuid.UUID, payload: PlanSchedule, db: DbSession, user: CurrentUser):
    """Set (replace) the plan's recurring weekly schedule. Stored on
    plan.metadata.schedule; the response includes the resolved dates and any
    run conflicts as warnings (conflicts are surfaced, not blocked)."""
    plan = get_owned(db, Plan, plan_id, user)
    metadata = dict(plan.metadata_ or {})
    metadata["schedule"] = payload.model_dump(by_alias=True, mode="json", exclude_none=True)
    plan.metadata_ = metadata
    db.commit()
    db.refresh(plan)
    return _build_schedule_response(db, user, plan)


@router.delete("/{plan_id}/schedule", response_model=PlanScheduleResponse)
def clear_plan_schedule(plan_id: uuid.UUID, db: DbSession, user: CurrentUser):
    """Remove the plan's recurring schedule."""
    plan = get_owned(db, Plan, plan_id, user)
    metadata = dict(plan.metadata_ or {})
    metadata.pop("schedule", None)
    plan.metadata_ = metadata
    db.commit()
    db.refresh(plan)
    return _build_schedule_response(db, user, plan)
