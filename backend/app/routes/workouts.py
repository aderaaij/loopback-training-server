import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.auth import CurrentUser
from app.data_consent import BODY, ConsentScope, CurrentConsent
from app.database import DbSession
from app.models.feedback import WorkoutFeedback
from app.models.plan import Plan
from app.models.queue import WorkoutQueue
from app.models.shoe import Shoe
from app.models.workout import Workout
from app.routes.queue import _scheduled_date_from_data
from app.schemas.workout import (
    WorkoutContextQueueItem,
    WorkoutContextRead,
    WorkoutCreate,
    WorkoutList,
    WorkoutPlanLinkUpdate,
    WorkoutRead,
    WorkoutShoeUpdate,
    WorkoutSummary,
)
from app.tenancy import get_owned
from app.workout_summary import downsample_timed, round_floats, strip_samples

router = APIRouter()

RUNNING_ACTIVITY = "running"


def _default_shoe_id(db: DbSession, user, payload: WorkoutCreate) -> uuid.UUID | None:
    """The pair a newly arrived run is assigned to: the athlete's default,
    for runs only. A run from before the pair was added gets nothing, because
    that distance is already in the pair's starting mileage; without this, a
    reinstall that re-uploads a year of runs would put them all on it."""
    if payload.activity_type != RUNNING_ACTIVITY:
        return None
    shoe = db.scalars(
        select(Shoe).where(Shoe.user_id == user.id, Shoe.is_default.is_(True), Shoe.retired_at.is_(None))
    ).first()
    if shoe is None:
        return None
    started = payload.start_date
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return shoe.id if started >= shoe.created_at else None


def _for_coach(workout: Workout, consent: ConsentScope, schema):
    """The workout as this caller may see it. Workouts are always shared, but
    VO2 max is a `body` figure: a coach-scoped read by an athlete who withholds
    `body` gets the workout with it blanked, the same choice that hides the
    daily figure."""
    if consent.allows(BODY):
        return workout
    read = schema.model_validate(workout)
    read.vo2_max = None
    return read


@router.post("", response_model=WorkoutRead, status_code=status.HTTP_201_CREATED)
def create_workout(payload: WorkoutCreate, db: DbSession, user: CurrentUser):
    existing = db.get(Workout, payload.id)
    if existing and existing.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Workout id belongs to another user")
    if existing:
        existing.activity_type = payload.activity_type
        existing.start_date = payload.start_date
        existing.end_date = payload.end_date
        existing.duration = payload.duration
        existing.total_distance = payload.total_distance
        existing.total_energy_burned = payload.total_energy_burned
        existing.source = payload.source
        # A link the athlete made or removed by hand outlives a re-upload,
        # which only carries the app's automatic match.
        if not existing.plan_link_manual:
            existing.plan_workout_id = payload.plan_workout_id
        existing.effort_score = payload.effort_score
        existing.estimated_effort_score = payload.estimated_effort_score
        existing.end_heart_rate = payload.end_heart_rate
        existing.heart_rate_after_1min = payload.heart_rate_after_1min
        existing.heart_rate_after_2min = payload.heart_rate_after_2min
        existing.vo2_max = payload.vo2_max
        existing.data = payload.data
        # shoe_id and shoe_confirmed are left alone: the app re-uploads
        # workouts, and that must not undo a pair the athlete picked or took
        # off, nor forget that they did.
        db.commit()
        db.refresh(existing)
        return existing

    workout = Workout(
        id=payload.id,
        user_id=user.id,
        activity_type=payload.activity_type,
        start_date=payload.start_date,
        end_date=payload.end_date,
        duration=payload.duration,
        total_distance=payload.total_distance,
        total_energy_burned=payload.total_energy_burned,
        source=payload.source,
        plan_workout_id=payload.plan_workout_id,
        effort_score=payload.effort_score,
        estimated_effort_score=payload.estimated_effort_score,
        end_heart_rate=payload.end_heart_rate,
        heart_rate_after_1min=payload.heart_rate_after_1min,
        heart_rate_after_2min=payload.heart_rate_after_2min,
        vo2_max=payload.vo2_max,
        data=payload.data,
        shoe_id=_default_shoe_id(db, user, payload),
    )
    db.add(workout)
    db.commit()
    db.refresh(workout)
    return workout


@router.get("", response_model=list[WorkoutList])
def list_workouts(
    db: DbSession,
    user: CurrentUser,
    consent: CurrentConsent,
    activity_type: str | None = None,
    start_after: datetime | None = None,
    start_before: datetime | None = None,
    plan_workout_id: uuid.UUID | None = None,
    shoe_id: uuid.UUID | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
):
    q = select(Workout).where(Workout.user_id == user.id).order_by(Workout.start_date.desc())

    if activity_type:
        q = q.where(Workout.activity_type == activity_type)
    if start_after:
        q = q.where(Workout.start_date >= start_after)
    if start_before:
        q = q.where(Workout.start_date <= start_before)
    if plan_workout_id:
        q = q.where(Workout.plan_workout_id == plan_workout_id)
    if shoe_id:
        q = q.where(Workout.shoe_id == shoe_id)

    q = q.offset(offset).limit(limit)
    return [_for_coach(w, consent, WorkoutList) for w in db.scalars(q).all()]


@router.get("/summary", response_model=list[WorkoutSummary])
def workout_summary(
    db: DbSession,
    user: CurrentUser,
    activity_type: str | None = None,
    period: str = Query(default="month", pattern="^(week|month|year)$"),
    start_after: datetime | None = None,
    start_before: datetime | None = None,
    limit: int | None = Query(default=None, ge=1, le=500),
):
    trunc = func.date_trunc(period, Workout.start_date)

    q = (
        select(
            trunc.label("period"),
            Workout.activity_type,
            func.count().label("count"),
            func.sum(Workout.total_distance).label("total_distance"),
            func.sum(Workout.duration).label("total_duration"),
            func.avg(Workout.total_distance).label("avg_distance"),
            func.avg(Workout.duration).label("avg_duration"),
            func.sum(Workout.total_energy_burned).label("total_energy_burned"),
        )
        .where(Workout.user_id == user.id)
        .group_by(trunc, Workout.activity_type)
        .order_by(trunc.desc())
    )

    if activity_type:
        q = q.where(Workout.activity_type == activity_type)
    if start_after:
        q = q.where(Workout.start_date >= start_after)
    if start_before:
        q = q.where(Workout.start_date <= start_before)
    if limit:
        # Rows are ordered newest-first, so a limit keeps the most recent
        # (period × activity_type) rows and history stays reachable via
        # start_before. Without it the response grows forever.
        q = q.limit(limit)

    rows = db.execute(q).all()
    return [
        WorkoutSummary(
            period=str(row.period),
            activity_type=row.activity_type,
            count=row.count,
            total_distance=round(row.total_distance, 1) if row.total_distance is not None else None,
            total_duration=round(row.total_duration, 1) if row.total_duration is not None else None,
            avg_distance=round(float(row.avg_distance), 1) if row.avg_distance else None,
            avg_duration=round(float(row.avg_duration), 1) if row.avg_duration else None,
            total_energy_burned=round(row.total_energy_burned, 1) if row.total_energy_burned is not None else None,
        )
        for row in rows
    ]


@router.get("/{workout_id}", response_model=WorkoutRead)
def get_workout(
    workout_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    consent: CurrentConsent,
    include_samples: bool = True,
):
    """Full workout detail. With `include_samples=false` the raw sample
    arrays in `data` (route GPS points, cadence, heart rate — ~600 kB for a
    GPS run) are replaced by a compact `data.samplesSummary`, and float noise
    is rounded away — root columns included, not just the blob."""
    workout = get_owned(db, Workout, workout_id, user)
    if include_samples:
        return _for_coach(workout, consent, WorkoutRead)
    read = WorkoutRead.model_validate(workout)
    if not consent.allows(BODY):
        read.vo2_max = None
    read.data = strip_samples(read.data)
    # The ORM float columns carry the same double-precision noise as the blob.
    for name, value in list(read):
        if isinstance(value, float):
            setattr(read, name, round(value, 2))
    return read


@router.get("/{workout_id}/splits")
def get_workout_splits(workout_id: uuid.UUID, db: DbSession, user: CurrentUser):
    workout = get_owned(db, Workout, workout_id, user)
    return round_floats(workout.data.get("splits", workout.data.get("events", [])))


@router.get("/{workout_id}/heartrate")
def get_workout_heartrate(
    workout_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    max_samples: int | None = Query(default=None, ge=16, le=5000),
):
    """Heart rate series. `max_samples` caps the series length by averaging
    over evenly-sized buckets — a workout's sample count is otherwise bounded
    only by its duration (a 3 h run is ~2000 samples)."""
    workout = get_owned(db, Workout, workout_id, user)
    samples = workout.data.get("heartRate", workout.data.get("heartRateSamples", []))
    if max_samples and isinstance(samples, list):
        samples = downsample_timed(samples, max_samples)
    return samples


def _context(db: DbSession, user, workout: Workout) -> WorkoutContextRead:
    queue_item = plan = feedback = None
    if workout.plan_workout_id is not None:
        queue_row = db.scalars(
            select(WorkoutQueue).where(
                WorkoutQueue.id == workout.plan_workout_id,
                WorkoutQueue.user_id == user.id,
            )
        ).first()
        if queue_row is not None:
            queue_item = WorkoutContextQueueItem.model_validate(queue_row)
            if queue_item.scheduled_date is None:
                queue_item.scheduled_date = _scheduled_date_from_data(queue_row.workout_data)
            if queue_row.plan_id is not None:
                plan = db.scalars(
                    select(Plan).where(Plan.id == queue_row.plan_id, Plan.user_id == user.id)
                ).first()
        # Feedback is keyed by the queue item id, so it survives queue deletion.
        feedback = db.scalars(
            select(WorkoutFeedback).where(
                WorkoutFeedback.workout_id == workout.plan_workout_id,
                WorkoutFeedback.user_id == user.id,
            )
        ).first()

    return WorkoutContextRead(
        workout_id=workout.id,
        plan_workout_id=workout.plan_workout_id,
        plan_link_manual=workout.plan_link_manual,
        queue_item=queue_item,
        plan=plan,
        feedback=feedback,
    )


@router.get("/{workout_id}/context", response_model=WorkoutContextRead)
def get_workout_context(workout_id: uuid.UUID, db: DbSession, user: CurrentUser):
    """Server-held linkage for a recorded workout: the queue item it fulfilled
    (via plan_workout_id), the plan behind that item, and any feedback filed
    against it. Every key is null for a workout that never matched a queued
    session, so clients can call this unconditionally."""
    return _context(db, user, get_owned(db, Workout, workout_id, user))


def _reopen_if_unfulfilled(db: DbSession, user, item_id: uuid.UUID) -> None:
    """A session that just lost its workout goes back to what it was before
    one counted for it: skipped if the athlete skipped it, otherwise delivered
    and not done. A session another workout still fulfils stays completed."""
    item = db.scalars(
        select(WorkoutQueue).where(WorkoutQueue.id == item_id, WorkoutQueue.user_id == user.id)
    ).first()
    if item is None or item.status != "completed":
        return
    still_fulfilled = db.scalars(
        select(Workout.id).where(Workout.user_id == user.id, Workout.plan_workout_id == item_id)
    ).first()
    if still_fulfilled is not None:
        return
    skipped = db.scalars(
        select(WorkoutFeedback.id).where(
            WorkoutFeedback.user_id == user.id,
            WorkoutFeedback.workout_id == item_id,
            WorkoutFeedback.action == "skip",
            WorkoutFeedback.dismissed.is_(False),
        )
    ).first()
    item.status = "skipped" if skipped is not None else "synced"
    item.completed_at = None


@router.put("/{workout_id}/plan-link", response_model=WorkoutContextRead)
def set_workout_plan_link(workout_id: uuid.UUID, body: WorkoutPlanLinkUpdate, db: DbSession, user: CurrentUser):
    """Count a recorded workout for a planned session, or stop counting it
    with `planWorkoutId: null`. This is the athlete correcting the record, so
    nothing about the two has to match: not the day, not the activity, not
    what was prescribed. A skipped session can be linked too.

    Linking completes the session, stamped with the workout's end. A session
    counts one workout, so whichever workout was linked to it before is
    unlinked. A session this workout leaves behind is reopened. Either way
    the link is marked manual and later uploads of the workout leave it alone.
    """
    workout = get_owned(db, Workout, workout_id, user)
    item = get_owned(db, WorkoutQueue, body.plan_workout_id, user) if body.plan_workout_id is not None else None
    previous_id = workout.plan_workout_id

    if item is not None:
        displaced = db.scalars(
            select(Workout).where(
                Workout.user_id == user.id,
                Workout.plan_workout_id == item.id,
                Workout.id != workout.id,
            )
        ).all()
        for other in displaced:
            other.plan_workout_id = None
            other.plan_link_manual = True
        item.status = "completed"
        item.completed_at = workout.end_date

    workout.plan_workout_id = item.id if item is not None else None
    workout.plan_link_manual = True
    db.flush()

    if previous_id is not None and previous_id != workout.plan_workout_id:
        _reopen_if_unfulfilled(db, user, previous_id)

    db.commit()
    db.refresh(workout)
    return _context(db, user, workout)


@router.put("/{workout_id}/shoe", response_model=WorkoutList)
def set_workout_shoe(
    workout_id: uuid.UUID, body: WorkoutShoeUpdate, db: DbSession, user: CurrentUser, consent: CurrentConsent
):
    """Assign a pair to a workout, or take it off with `shoeId: null`. Any
    activity type and a retired pair are both fine: this is the athlete
    correcting the record, not the automatic default. Either way the pair
    counts as checked from here on, including when it is set to the one the
    workout already had."""
    workout = get_owned(db, Workout, workout_id, user)
    if body.shoe_id is not None:
        get_owned(db, Shoe, body.shoe_id, user)  # 404s if the pair isn't the caller's
    workout.shoe_id = body.shoe_id
    workout.shoe_confirmed = True
    db.commit()
    db.refresh(workout)
    return _for_coach(workout, consent, WorkoutList)


@router.delete("/{workout_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workout(workout_id: uuid.UUID, db: DbSession, user: CurrentUser):
    workout = get_owned(db, Workout, workout_id, user)
    db.delete(workout)
    db.commit()
