"""Derive per-night sleep totals from raw HealthKit samples.

Pure functions, no DB access — unit-tested in tests/test_sleep_merge.py.
DB assembly lives in app/sleep_service.py.

Semantics:
- The night attributed to date D is the local window [noon D-1, noon D).
  Midnight-based attribution bisects every pre-midnight bedtime; noon-based
  puts a whole night on the date of the morning it ends.
- Overlapping samples never sum. A sweep line over sample edges assigns each
  time slice to exactly one winner: specific stages (rem/core/deep/awake)
  beat `unspecified`; ties break deterministically by source then start.
- `in_bed` is bed occupancy, not sleep — it never competes and never counts.
- `unspecified`-won time folds into `core` in the rollup, matching what the
  app historically reported for unstaged sleep, so the stored/wire shape of
  sleep_stages is unchanged. The raw samples retain the distinction.
- duration = rem + core + deep. Awake is reported but never counted.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo

NOON = time(12, 0)


def _utc(ts: datetime) -> datetime:
    # All interval arithmetic happens in UTC: Python subtracts two datetimes
    # that share a tzinfo object by wall clock (no offset adjustment), which
    # silently drops the repeated hour across a DST fall-back.
    return ts.astimezone(timezone.utc)

# Higher wins a slice. in_bed is deliberately absent: it overlaps every real
# stage across the whole night and must never claim (or inflate) sleep time.
_STAGE_PRIORITY = {"rem": 2, "core": 2, "deep": 2, "awake": 2, "unspecified": 1}


@dataclass(frozen=True)
class Sample:
    start: datetime  # tz-aware
    end: datetime  # tz-aware, > start
    stage: str
    source: str


def night_window(day: date, tz: tzinfo) -> tuple[datetime, datetime]:
    """[noon the day before, noon that day) in local time."""
    return (
        datetime.combine(day - timedelta(days=1), NOON, tzinfo=tz),
        datetime.combine(day, NOON, tzinfo=tz),
    )


def attribution_date(ts: datetime, tz: tzinfo) -> date:
    """The date whose night window contains this instant."""
    local = ts.astimezone(tz)
    return local.date() + timedelta(days=1) if local.time() >= NOON else local.date()


def nights_touched(samples: list[Sample], tz: tzinfo) -> set[date]:
    """Every attribution date any sample overlaps (a sample can span windows)."""
    days: set[date] = set()
    for s in samples:
        d = attribution_date(s.start, tz)
        # end is an exclusive bound: a sample ending exactly at noon
        # contributes nothing to the next window.
        last = attribution_date(s.end - timedelta(microseconds=1), tz)
        while d <= last:
            days.add(d)
            d += timedelta(days=1)
    return days


def merge_window(samples: list[Sample], win_start: datetime, win_end: datetime) -> dict[str, float]:
    """Seconds per stage inside [win_start, win_end), one winner per slice."""
    win_start, win_end = _utc(win_start), _utc(win_end)
    clipped: list[tuple[datetime, datetime, Sample]] = []
    for s in samples:
        if s.stage not in _STAGE_PRIORITY:
            continue
        start, end = max(_utc(s.start), win_start), min(_utc(s.end), win_end)
        if start < end:
            clipped.append((start, end, s))

    edges = sorted({t for start, end, _ in clipped for t in (start, end)})
    totals: dict[str, float] = {}
    for t0, t1 in zip(edges, edges[1:]):
        covering = [s for start, end, s in clipped if start <= t0 and end >= t1]
        if not covering:
            continue
        winner = max(covering, key=lambda s: (_STAGE_PRIORITY[s.stage], s.source, s.start))
        totals[winner.stage] = totals.get(winner.stage, 0.0) + (t1 - t0).total_seconds()
    return totals


def derive_night(samples: list[Sample], day: date, tz: tzinfo) -> tuple[float, dict[str, float]] | None:
    """(sleep_duration, sleep_stages) for one night, or None if no sleep time."""
    totals = merge_window(samples, *night_window(day, tz))
    stages: dict[str, float] = {}
    for stage in ("awake", "rem", "core", "deep"):
        if totals.get(stage, 0.0) > 0:
            stages[stage] = totals[stage]
    if totals.get("unspecified", 0.0) > 0:
        stages["core"] = stages.get("core", 0.0) + totals["unspecified"]
    duration = sum(stages.get(k, 0.0) for k in ("rem", "core", "deep"))
    if duration <= 0:
        return None
    return duration, stages
