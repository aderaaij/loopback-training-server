from datetime import date, datetime, time, timedelta, timezone as dt_timezone

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.auth import CurrentUser
from app.database import DbSession
from app.models.sleep_sample import SleepSample
from app.schemas.sleep import (
    SleepRederiveRequest,
    SleepRederiveResponse,
    SleepSampleRead,
    SleepSamplesBulkCreate,
    SleepSamplesBulkResponse,
    parse_timezone,
)
from app.sleep_merge import Sample, nights_touched
from app.sleep_service import rederive_sleep

router = APIRouter()


@router.post("/samples", response_model=SleepSamplesBulkResponse)
def upload_samples(payload: SleepSamplesBulkCreate, db: DbSession, user: CurrentUser):
    tz = parse_timezone(payload.timezone)

    rows = [
        {
            "user_id": user.id,
            "start_at": s.start,
            "end_at": s.end,
            "stage": s.stage,
            "source": s.source,
        }
        for s in payload.samples
    ]
    # Chunked so a large backfill stays under Postgres's 65535-parameter cap.
    stored = 0
    for i in range(0, len(rows), 5000):
        stored += len(
            db.execute(
                insert(SleepSample)
                .values(rows[i : i + 5000])
                .on_conflict_do_nothing(constraint="uq_sleep_samples_identity")
                .returning(SleepSample.id)
            ).all()
        )

    days = nights_touched(
        [Sample(start=s.start, end=s.end, stage=s.stage, source=s.source) for s in payload.samples], tz
    )
    days_updated = rederive_sleep(db, user.id, days, tz)
    db.commit()

    return SleepSamplesBulkResponse(received=len(payload.samples), stored=stored, days_updated=days_updated)


@router.get("/samples", response_model=list[SleepSampleRead])
def list_samples(
    db: DbSession,
    user: CurrentUser,
    start_date: date = Query(...),
    end_date: date | None = None,
):
    """Raw samples whose span overlaps [start_date, end_date] (UTC days).

    Diagnostic view — this is how overlapping/duplicate sources get attributed.
    """
    win_start = datetime.combine(start_date, time.min, tzinfo=dt_timezone.utc)
    q = select(SleepSample).where(SleepSample.user_id == user.id, SleepSample.end_at > win_start)
    if end_date:
        win_end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=dt_timezone.utc)
        q = q.where(SleepSample.start_at < win_end)
    return db.scalars(q.order_by(SleepSample.start_at, SleepSample.source)).all()


@router.post("/rederive", response_model=SleepRederiveResponse)
def rederive(payload: SleepRederiveRequest, db: DbSession, user: CurrentUser):
    """Recompute daily rollups from stored samples — lets merge-logic changes
    be applied to history without any client involvement."""
    tz = parse_timezone(payload.timezone)
    days = {
        payload.start_date + timedelta(days=i)
        for i in range((payload.end_date - payload.start_date).days + 1)
    }
    days_updated = rederive_sleep(db, user.id, days, tz)
    db.commit()
    return SleepRederiveResponse(days_updated=days_updated)
