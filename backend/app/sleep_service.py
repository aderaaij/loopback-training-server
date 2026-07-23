"""DB assembly around app/sleep_merge.py: load a user's raw sleep samples and
(re)derive the daily rollups in daily_health_metrics.

The rollup write is change-detected: re-deriving over unchanged samples is a
true no-op (no UPDATE, no updated_at bump) so the derivation can be re-run
freely after merge-logic changes.
"""

import uuid
from datetime import date, tzinfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.health_metrics import DailyHealthMetrics
from app.models.sleep_sample import SleepSample
from app.sleep_merge import Sample, derive_night, night_window


def user_has_sleep_samples(db: Session, user_id: uuid.UUID) -> bool:
    return db.scalar(select(SleepSample.id).where(SleepSample.user_id == user_id).limit(1)) is not None


def _load_samples(db: Session, user_id: uuid.UUID, days: set[date], tz: tzinfo) -> list[Sample]:
    starts, ends = zip(*(night_window(d, tz) for d in days))
    rows = db.scalars(
        select(SleepSample).where(
            SleepSample.user_id == user_id,
            SleepSample.end_at > min(starts),
            SleepSample.start_at < max(ends),
        )
    ).all()
    return [Sample(start=r.start_at, end=r.end_at, stage=r.stage, source=r.source) for r in rows]


def _close_enough(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and abs(a - b) < 1e-6


def _stages_match(existing: dict | None, derived: dict[str, float]) -> bool:
    if existing is None:
        return False
    keys = set(existing) | set(derived)
    return all(_close_enough(existing.get(k), derived.get(k)) for k in keys)


def rederive_sleep(db: Session, user_id: uuid.UUID, days: set[date], tz: tzinfo) -> list[date]:
    """Recompute the sleep rollup for the given attribution dates from stored
    samples. Returns the dates actually written. Does not commit."""
    if not days:
        return []

    samples = _load_samples(db, user_id, days, tz)
    existing = {
        m.date: m
        for m in db.scalars(
            select(DailyHealthMetrics).where(
                DailyHealthMetrics.user_id == user_id, DailyHealthMetrics.date.in_(days)
            )
        )
    }

    written: list[date] = []
    for day in sorted(days):
        derived = derive_night(samples, day, tz)
        if derived is None:
            # No sleep found for this night — leave any existing row alone
            # rather than zeroing it (missing samples shouldn't erase data).
            continue
        duration, stages = derived

        row = existing.get(day)
        if row is not None and _close_enough(row.sleep_duration, duration) and _stages_match(row.sleep_stages, stages):
            continue

        stmt = insert(DailyHealthMetrics).values(
            user_id=user_id, date=day, sleep_duration=duration, sleep_stages=stages
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_daily_health_metrics_user_date",
            set_={"sleep_duration": duration, "sleep_stages": stages, "updated_at": func.now()},
        )
        db.execute(stmt)
        written.append(day)

    return written
