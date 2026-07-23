from datetime import date

from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.auth import CurrentUser
from app.database import DbSession
from app.models.health_metrics import DailyHealthMetrics
from app.schemas.health_metrics import (
    HealthMetricsBulkCreate,
    HealthMetricsBulkResponse,
    HealthMetricsRead,
)
from app.sleep_service import user_has_sleep_samples

router = APIRouter()

# Metric columns that can be upserted (excluding id, date, created_at, updated_at)
_METRIC_COLUMNS = [
    "sleep_duration", "sleep_stages", "resting_heart_rate", "hrv_sdnn",
    "weight", "vo2_max", "steps", "active_energy_burned",
    "body_fat_percentage", "lean_body_mass", "respiratory_rate", "spo2",
]

# Once a user ships raw sleep samples, their daily sleep is derived server-side
# (app/sleep_service.py) and client-aggregated values are ignored — an older
# app build syncing partial windows must not clobber the derived rollup.
_DERIVED_SLEEP_COLUMNS = {"sleep_duration", "sleep_stages"}


@router.post("", response_model=HealthMetricsBulkResponse)
def bulk_upsert_metrics(payload: HealthMetricsBulkCreate, db: DbSession, user: CurrentUser):
    sleep_is_derived = user_has_sleep_samples(db, user.id)
    upserted = 0
    for metric in payload.metrics:
        values = {"user_id": user.id, "date": metric.date}
        # Only include non-null fields so we don't overwrite existing data
        set_on_conflict = {}
        for col in _METRIC_COLUMNS:
            if sleep_is_derived and col in _DERIVED_SLEEP_COLUMNS:
                continue
            val = getattr(metric, col)
            if col == "sleep_stages" and val is not None:
                val = val.model_dump(exclude_none=True)
            if val is not None:
                values[col] = val
                set_on_conflict[col] = val

        stmt = insert(DailyHealthMetrics).values(**values)
        if set_on_conflict:
            stmt = stmt.on_conflict_do_update(
                constraint="uq_daily_health_metrics_user_date",
                # updated_at must be set explicitly: the ORM-level onupdate
                # does not fire for Core ON CONFLICT DO UPDATE, which is how
                # rewrites stayed invisible during the sleep-corruption bug.
                set_={**set_on_conflict, "updated_at": func.now()},
            )
        else:
            stmt = stmt.on_conflict_do_nothing(constraint="uq_daily_health_metrics_user_date")

        db.execute(stmt)
        upserted += 1

    db.commit()
    return HealthMetricsBulkResponse(upserted=upserted)


@router.get("", response_model=list[HealthMetricsRead])
def list_metrics(
    db: DbSession,
    user: CurrentUser,
    start_date: date = Query(...),
    end_date: date | None = None,
):
    q = (
        select(DailyHealthMetrics)
        .where(DailyHealthMetrics.user_id == user.id, DailyHealthMetrics.date >= start_date)
        .order_by(DailyHealthMetrics.date.desc())
    )
    if end_date:
        q = q.where(DailyHealthMetrics.date <= end_date)

    return db.scalars(q).all()
