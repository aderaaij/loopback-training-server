from datetime import date, datetime, time, timedelta, timezone as dt_timezone

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.auth import CurrentUser
from app.database import DbSession
from app.models.health_metrics import DailyHealthMetrics
from app.models.nutrition import NUTRIENT_COLUMNS, UPSERT_COLUMNS, DailyNutrition
from app.models.workout import Workout
from app.nutrition_summary import EnergyDay, NutritionDay, WeightPoint, WorkoutLoad, summarize
from app.schemas.nutrition import (
    NutritionBulkCreate,
    NutritionBulkResponse,
    NutritionDeleteResponse,
    NutritionPeriod,
    NutritionRead,
    NutritionSummary,
)
from app.schemas.sleep import parse_timezone

router = APIRouter()


@router.post("", response_model=NutritionBulkResponse)
def bulk_upsert_nutrition(payload: NutritionBulkCreate, db: DbSession, user: CurrentUser):
    """Upsert whole days of dietary totals.

    Same contract as health metrics: omitted (null) fields never overwrite
    stored values, so an app build that only knows about energy and macros can
    ship alongside one that also reports micronutrients.

    That rule leaves a client unable to retract what it has stopped reporting,
    so `clear` names fields to null explicitly — omission is "no opinion",
    `clear` is "known absent". Without it a value the client no longer stands
    behind (a micronutrient it has since learned is a sparse sum) would
    outlive that decision forever.

    Values are whole-day totals and this overwrites field-by-field, so the
    client must compute them over a *complete* local day. A window whose edge
    lands mid-day would store that day's tail — the mechanism behind the July
    2026 sleep/steps corruption (docs/sleep-data-handoff.md). Days still in
    progress belong here with `partial: true`, which keeps them out of every
    average until a later sync completes them.
    """
    upserted = 0
    for day in payload.days:
        values = {"user_id": user.id, "date": day.date}
        set_on_conflict = {}
        for col in UPSERT_COLUMNS:
            val = getattr(day, col)
            if val is not None:
                values[col] = val
                set_on_conflict[col] = val

        for col in day.clear or ():
            values[col] = None
            set_on_conflict[col] = None

        stmt = insert(DailyNutrition).values(**values)
        if set_on_conflict:
            stmt = stmt.on_conflict_do_update(
                constraint="uq_daily_nutrition_user_date",
                # Explicit, because the ORM-level onupdate does not fire for a
                # Core ON CONFLICT DO UPDATE — that silence is what hid the
                # sleep rewrites for weeks.
                set_={**set_on_conflict, "updated_at": func.now()},
            )
        else:
            stmt = stmt.on_conflict_do_nothing(constraint="uq_daily_nutrition_user_date")

        db.execute(stmt)
        upserted += 1

    db.commit()
    return NutritionBulkResponse(upserted=upserted)


@router.get("", response_model=list[NutritionRead])
def list_nutrition(
    db: DbSession,
    user: CurrentUser,
    start_date: date = Query(...),
    end_date: date | None = None,
    limit: int | None = Query(default=None, ge=1, le=1000),
):
    """Daily rows, newest first. Days with no logged food have no row at all."""
    q = (
        select(DailyNutrition)
        .where(DailyNutrition.user_id == user.id, DailyNutrition.date >= start_date)
        .order_by(DailyNutrition.date.desc())
    )
    if end_date:
        q = q.where(DailyNutrition.date <= end_date)
    if limit:
        q = q.limit(limit)

    return db.scalars(q).all()


@router.delete("/{day}", response_model=NutritionDeleteResponse)
def delete_nutrition_day(day: date, db: DbSession, user: CurrentUser):
    """Remove a whole day's row.

    For data that should never have been stored at all — a stray day a backfill
    swept in, or a row from a source since found untrustworthy. To retract
    individual fields while keeping the day, use `clear` on the upsert instead.
    """
    row = db.scalar(
        select(DailyNutrition).where(
            DailyNutrition.user_id == user.id, DailyNutrition.date == day
        )
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"No nutrition row for {day}"
        )
    db.delete(row)
    db.commit()
    return NutritionDeleteResponse(date=day, deleted=1)


@router.get("/summary", response_model=NutritionSummary)
def nutrition_summary(
    db: DbSession,
    user: CurrentUser,
    start_date: date = Query(...),
    end_date: date | None = None,
    period: str = Query(default="week", pattern="^(week|month)$"),
    timezone: str | None = Query(
        default=None,
        description="IANA zone used to attribute workouts to a day (default UTC). "
        "Nutrition and weight are already keyed by local date.",
    ),
):
    """Intake, body weight and training load aligned on the same periods.

    This is the endpoint for "is my diet supporting my training?" — comparing
    average intake against weight movement and the load that earned it, without
    the caller having to align three series by hand.
    """
    end = end_date or date.today()
    if end < start_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="end_date must not precede start_date"
        )
    try:
        tz = parse_timezone(timezone) if timezone else dt_timezone.utc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    nutrition_rows = db.scalars(
        select(DailyNutrition).where(
            DailyNutrition.user_id == user.id,
            DailyNutrition.date >= start_date,
            DailyNutrition.date <= end,
        )
    ).all()
    days = [
        NutritionDay(
            day=r.date,
            values={col: getattr(r, col) for col in NUTRIENT_COLUMNS},
            partial=r.partial,
        )
        for r in nutrition_rows
    ]

    weight_rows = db.execute(
        select(DailyHealthMetrics.date, DailyHealthMetrics.weight).where(
            DailyHealthMetrics.user_id == user.id,
            DailyHealthMetrics.date >= start_date,
            DailyHealthMetrics.date <= end,
            DailyHealthMetrics.weight.is_not(None),
        )
    ).all()
    weights = [WeightPoint(day=r.date, weight=r.weight) for r in weight_rows]

    energy_rows = db.execute(
        select(
            DailyHealthMetrics.date,
            DailyHealthMetrics.active_energy_burned,
            DailyHealthMetrics.basal_energy_burned,
        ).where(
            DailyHealthMetrics.user_id == user.id,
            DailyHealthMetrics.date >= start_date,
            DailyHealthMetrics.date <= end,
        )
    ).all()
    energy = [
        EnergyDay(day=r.date, active_kcal=r.active_energy_burned, basal_kcal=r.basal_energy_burned)
        for r in energy_rows
    ]
    # Health metrics have no `partial` flag, so a day still in progress stores
    # only the hours elapsed and would read as a genuinely low-burn day. Trust
    # expenditure only through the athlete's local yesterday.
    complete_through = datetime.now(tz).date() - timedelta(days=1)

    # Widen the workout window by a day on each side: a local-date attribution
    # can pull a workout in from the neighbouring UTC day. summarize() drops
    # anything that still falls outside the window.
    win_start = datetime.combine(start_date - timedelta(days=1), time.min, tzinfo=dt_timezone.utc)
    win_end = datetime.combine(end + timedelta(days=2), time.min, tzinfo=dt_timezone.utc)
    workout_rows = db.execute(
        select(
            Workout.start_date,
            Workout.total_distance,
            Workout.duration,
            Workout.total_energy_burned,
        ).where(
            Workout.user_id == user.id,
            Workout.start_date >= win_start,
            Workout.start_date < win_end,
        )
    ).all()
    loads = [
        WorkoutLoad(
            day=r.start_date.astimezone(tz).date(),
            distance_m=r.total_distance,
            duration_s=r.duration,
            energy_kcal=r.total_energy_burned,
        )
        for r in workout_rows
    ]

    periods = summarize(
        days,
        weights,
        loads,
        start_date,
        end,
        period,
        energy=energy,
        complete_through=complete_through,
    )
    return NutritionSummary(
        period=period,
        start_date=start_date,
        end_date=end,
        periods=[NutritionPeriod(**p) for p in periods],
    )
