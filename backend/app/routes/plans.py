import uuid
from datetime import date, datetime, time, timezone

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, or_, select

from app.auth import CurrentUser
from app.database import DbSession
from app.models.plan import SCHEDULED_STATUSES, Plan
from app.models.plan_note import PlanNote
from app.models.queue import WorkoutQueue
from app.models.user import User
from app.models.workout import Workout
from app.routes.schedule import STRENGTH_ACTIVITY
from app.schedule_utils import normalize_schedule, resolve_sessions
from app.schemas.plan import (
    PlanCompleteRequest,
    PlanCompleteResponse,
    PlanCreate,
    PlanProgress,
    PlanRead,
    PlanSchedule,
    PlanScheduleResponse,
    PlanUpdate,
    ScheduledSession,
    ScheduleSession,
    ScheduleSessionMove,
)
from app.schemas.queue import QueueItemRead
from app.schemas.validation import PlanValidateResponse
from app.tenancy import get_owned
from app.validation_service import run_validation

router = APIRouter()


def _progress_by_plan(db: DbSession, user: User, plans: list[Plan]) -> dict[uuid.UUID, PlanProgress]:
    """Session counts per plan: queued runs (one grouped query for the batch)
    plus, for plans carrying a recurring schedule, the scheduled strength
    sessions — completed when a strength workout landed on the session's date
    (the same date-matching the calendar's `completed` flag uses), skipped
    when the date passed unmatched, remaining otherwise."""
    if not plans:
        return {}
    rows = db.execute(
        select(WorkoutQueue.plan_id, WorkoutQueue.status, func.count())
        .where(WorkoutQueue.user_id == user.id, WorkoutQueue.plan_id.in_([p.id for p in plans]))
        .group_by(WorkoutQueue.plan_id, WorkoutQueue.status)
    ).all()
    out: dict[uuid.UUID, PlanProgress] = {}
    for plan_id, run_status, count in rows:
        p = out.setdefault(plan_id, PlanProgress())
        p.runs_total += count
        if run_status == "completed":
            p.runs_completed += count
        elif run_status == "skipped":
            p.runs_skipped += count
        else:
            p.runs_remaining += count

    sessions_by_plan = {p.id: resolve_sessions((p.metadata_ or {}).get("schedule")) for p in plans}
    dates = [s["date"] for sessions in sessions_by_plan.values() for s in sessions]
    if dates:
        done_dates = {
            start.date()
            for start in db.scalars(
                select(Workout.start_date).where(
                    Workout.user_id == user.id,
                    Workout.activity_type == STRENGTH_ACTIVITY,
                    Workout.start_date >= datetime.combine(min(dates), time.min, tzinfo=timezone.utc),
                    Workout.start_date <= datetime.combine(max(dates), time.max, tzinfo=timezone.utc),
                )
            )
        }
        today = datetime.now(timezone.utc).date()
        for plan_id, sessions in sessions_by_plan.items():
            for s in sessions:
                p = out.setdefault(plan_id, PlanProgress())
                p.runs_total += 1
                if s["date"] in done_dates:
                    p.runs_completed += 1
                elif s["date"] < today:
                    p.runs_skipped += 1
                else:
                    p.runs_remaining += 1
    return out


def _is_finishable(plan: Plan, progress: PlanProgress, today: date) -> bool:
    """An active plan that looks done: its window has passed, or every session
    (queued run or scheduled strength day) is retired, with at least one
    actually completed — a fully-skipped plan the day it's created shouldn't
    celebrate.

    An empty queue only counts once the end date is reached. A plan filled in
    a week at a time has every session done at the end of each week, months
    before it is over."""
    if plan.status != "active" or plan.start_date > today:
        return False
    window_over = plan.end_date is not None and plan.end_date < today
    all_runs_done = (
        progress.runs_total > 0
        and progress.runs_remaining == 0
        and progress.runs_completed > 0
    )
    ends_later = plan.end_date is not None and plan.end_date > today
    return window_over or (all_runs_done and not ends_later)


def _plan_read(plan: Plan, progress: PlanProgress, today: date) -> PlanRead:
    out = PlanRead.model_validate(plan)
    out.progress = progress
    out.finishable = _is_finishable(plan, progress, today)
    return out


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
            WorkoutQueue.status != "skipped",  # a skipped run no longer occupies its day
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
            recurring=s["recurring"],
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
    return _plan_read(plan, _progress_by_plan(db, user, [plan]).get(plan.id, PlanProgress()),
                      datetime.now(timezone.utc).date())


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

    plans = db.scalars(q).all()
    progress = _progress_by_plan(db, user, plans)
    today = datetime.now(timezone.utc).date()
    return [_plan_read(p, progress.get(p.id, PlanProgress()), today) for p in plans]


@router.get("/{plan_id}", response_model=PlanRead)
def get_plan(plan_id: uuid.UUID, db: DbSession, user: CurrentUser):
    plan = get_owned(db, Plan, plan_id, user)
    progress = _progress_by_plan(db, user, [plan])
    return _plan_read(plan, progress.get(plan.id, PlanProgress()), datetime.now(timezone.utc).date())


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
    return _plan_read(plan, _progress_by_plan(db, user, [plan]).get(plan.id, PlanProgress()),
                      datetime.now(timezone.utc).date())


@router.post("/{plan_id}/complete", response_model=PlanCompleteResponse)
def complete_plan(plan_id: uuid.UUID, payload: PlanCompleteRequest, db: DbSession, user: CurrentUser):
    """Wrap up an active plan: set status to completed, stamp
    metadata.completion, and store the athlete's feedback as a
    kind="feedback" plan note so the coach LLM sees it in get_plan_context.
    The response includes ``next_plan`` — another already-active plan of the
    same activity — so the UI knows whether to suggest planning the next block.
    """
    plan = get_owned(db, Plan, plan_id, user)
    if plan.status != "active":
        raise HTTPException(status_code=400, detail="Only an active plan can be completed")

    today = datetime.now(timezone.utc).date()
    completion: dict = {"completed_on": today.isoformat()}
    if payload.rating is not None:
        completion["rating"] = payload.rating
    if payload.feedback:
        completion["feedback"] = payload.feedback
    metadata = dict(plan.metadata_ or {})
    metadata["completion"] = completion
    plan.metadata_ = metadata
    plan.status = "completed"

    if payload.feedback or payload.rating is not None:
        summary = f"Plan wrap-up: {plan.name}"
        if payload.rating is not None:
            summary += f" — rated {payload.rating}/5"
        db.add(
            PlanNote(
                user_id=user.id,
                plan_id=plan.id,
                kind="feedback",
                summary=summary[:280],
                body=payload.feedback,
                importance=2,
            )
        )

    next_plan = db.scalars(
        select(Plan)
        .where(
            Plan.user_id == user.id,
            Plan.id != plan.id,
            # An already-built next block is usually "upcoming", not "active" —
            # filtering to active returned null and nudged the athlete to go
            # plan something that already existed.
            Plan.status.in_(SCHEDULED_STATUSES),
            Plan.activity_type == plan.activity_type,
            or_(Plan.end_date.is_(None), Plan.end_date >= today),
        )
        .order_by(Plan.start_date)
    ).first()

    db.commit()
    db.refresh(plan)

    progress = _progress_by_plan(db, user, [plan] + ([next_plan] if next_plan else []))
    return PlanCompleteResponse(
        plan=_plan_read(plan, progress.get(plan.id, PlanProgress()), today),
        next_plan=_plan_read(next_plan, progress.get(next_plan.id, PlanProgress()), today) if next_plan else None,
    )


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


@router.post("/{plan_id}/validate", response_model=PlanValidateResponse)
def validate_plan(plan_id: uuid.UUID, db: DbSession, user: CurrentUser):
    """Deterministic soundness check of the athlete's upcoming schedule with
    this plan's context (guardrails, race date). Warnings never block — they
    exist so the coach (LLM or human) sees the numbers before committing."""
    plan = get_owned(db, Plan, plan_id, user)
    warnings, weeks = run_validation(db, user, plan)
    return PlanValidateResponse(plan_id=plan.id, warnings=warnings, weeks=weeks)


@router.get("/{plan_id}/schedule", response_model=PlanScheduleResponse)
def get_plan_schedule(plan_id: uuid.UUID, db: DbSession, user: CurrentUser):
    """Return the plan's recurring schedule expanded into concrete dated
    sessions, each flagged where it collides with a queued run."""
    plan = get_owned(db, Plan, plan_id, user)
    return _build_schedule_response(db, user, plan)


def _strength_plan(db: DbSession, user: User, plan_id: uuid.UUID) -> Plan:
    """The plan, for a schedule write. Rejects a non-strength plan: a schedule
    marks gym days, and hanging one on a running plan silently mis-types
    everything downstream — the plan's session counts absorb the strength
    days, and the iOS app renders it as a gym cycle purely because a schedule
    is present. Guarded on write only; readers stay permissive so an existing
    plan can't 404 retroactively."""
    plan = get_owned(db, Plan, plan_id, user)
    if plan.activity_type != "strength":
        raise HTTPException(
            status_code=400,
            detail=(
                f"Schedules are for strength plans; this plan's activity_type is "
                f"'{plan.activity_type}'. Create a separate activity_type='strength' "
                f"plan for the gym cycle."
            ),
        )
    return plan


def _store_schedule(db: DbSession, user: User, plan: Plan, schedule: dict) -> PlanScheduleResponse:
    """Write a schedule back to the plan; one with nothing left in it is removed."""
    metadata = dict(plan.metadata_ or {})
    normalized = normalize_schedule(schedule)
    if normalized is None:
        metadata.pop("schedule", None)
    else:
        metadata["schedule"] = normalized
    plan.metadata_ = metadata
    db.commit()
    db.refresh(plan)
    return _build_schedule_response(db, user, plan)


def _sessions_on(schedule: dict, day: date) -> list[dict]:
    found = [s for s in resolve_sessions(schedule) if s["date"] == day]
    if not found:
        raise HTTPException(status_code=404, detail=f"No strength session scheduled on {day.isoformat()}")
    return found


def _without_day(schedule: dict, day: date, found: list[dict]) -> dict:
    """The schedule with every session on `day` taken out: individual ones are
    dropped, and a weekly occurrence is skipped for that date only."""
    out = dict(schedule)
    out["sessions"] = [s for s in out.get("sessions") or [] if str(s.get("date"))[:10] != day.isoformat()]
    if any(s["recurring"] for s in found):
        out["skipDates"] = [*(out.get("skipDates") or []), day.isoformat()]
    return out


@router.put("/{plan_id}/schedule", response_model=PlanScheduleResponse)
def set_plan_schedule(plan_id: uuid.UUID, payload: PlanSchedule, db: DbSession, user: CurrentUser):
    """Set (replace) the plan's schedule: a weekly recurrence, individual
    dated sessions, or both. Stored on plan.metadata.schedule; the response
    includes the resolved dates and any run conflicts as warnings (conflicts
    are surfaced, not blocked). Strength plans only.
    """
    plan = _strength_plan(db, user, plan_id)
    return _store_schedule(db, user, plan, payload.model_dump(by_alias=True, mode="json", exclude_none=True))


@router.post("/{plan_id}/schedule/sessions", response_model=PlanScheduleResponse)
def add_schedule_session(plan_id: uuid.UUID, payload: ScheduleSession, db: DbSession, user: CurrentUser):
    """Add one strength session on its own date, leaving the rest of the
    schedule alone. Starts a schedule when the plan has none, so a plan can be
    made of individual sessions only. Adding the same title on the same date
    again replaces it."""
    plan = _strength_plan(db, user, plan_id)
    schedule = dict((plan.metadata_ or {}).get("schedule") or {})
    schedule["sessions"] = [
        *(schedule.get("sessions") or []),
        payload.model_dump(by_alias=True, mode="json", exclude_none=True),
    ]
    return _store_schedule(db, user, plan, schedule)


@router.delete("/{plan_id}/schedule/sessions/{day}", response_model=PlanScheduleResponse)
def remove_schedule_session(plan_id: uuid.UUID, day: date, db: DbSession, user: CurrentUser):
    """Take the session(s) on one date off the schedule. An individual session
    is removed; a weekly occurrence is skipped for that date and keeps
    recurring. 404 when nothing is scheduled that day."""
    plan = _strength_plan(db, user, plan_id)
    schedule = dict((plan.metadata_ or {}).get("schedule") or {})
    return _store_schedule(db, user, plan, _without_day(schedule, day, _sessions_on(schedule, day)))


@router.post("/{plan_id}/schedule/sessions/{day}/move", response_model=PlanScheduleResponse)
def move_schedule_session(
    plan_id: uuid.UUID, day: date, payload: ScheduleSessionMove, db: DbSession, user: CurrentUser
):
    """Move the session(s) on one date to another date, keeping title and
    routine. A weekly occurrence moves for that week only. 404 when nothing is
    scheduled on the date moved from."""
    plan = _strength_plan(db, user, plan_id)
    schedule = dict((plan.metadata_ or {}).get("schedule") or {})
    found = _sessions_on(schedule, day)
    if payload.to == day:
        return _build_schedule_response(db, user, plan)
    moved = _without_day(schedule, day, found)
    moved["sessions"] = [
        *moved["sessions"],
        *(
            {"date": payload.to.isoformat(), "title": s["title"], "routineId": s["routineId"]}
            for s in found
        ),
    ]
    return _store_schedule(db, user, plan, moved)


@router.delete("/{plan_id}/schedule", response_model=PlanScheduleResponse)
def clear_plan_schedule(plan_id: uuid.UUID, db: DbSession, user: CurrentUser):
    """Remove the plan's whole schedule, weekly pattern and dated sessions alike."""
    plan = get_owned(db, Plan, plan_id, user)
    metadata = dict(plan.metadata_ or {})
    metadata.pop("schedule", None)
    plan.metadata_ = metadata
    db.commit()
    db.refresh(plan)
    return _build_schedule_response(db, user, plan)
