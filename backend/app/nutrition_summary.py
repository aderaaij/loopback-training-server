"""Pure period aggregation: diet against body weight against training load.

The point of this module is that the three series an athlete actually wants
correlated — intake, weight, and load — live in three different tables on three
different cadences. Aligning them client-side (or LLM-side) means re-deriving
week boundaries every time and getting them subtly wrong. So the alignment
happens once, here, over plain values with no DB or ORM involvement.

Bucketing is done in Python rather than SQL `date_trunc` on purpose: nutrition
is keyed by a local calendar date while workouts carry an instant, and letting
Postgres truncate a timestamptz in the session timezone would drift a late
evening workout into the neighbouring week.
"""

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta

from app.models.nutrition import NUTRIENT_COLUMNS


@dataclass(frozen=True)
class NutritionDay:
    day: date
    values: dict[str, float | None]
    partial: bool = False


@dataclass(frozen=True)
class WeightPoint:
    day: date
    weight: float


@dataclass(frozen=True)
class WorkoutLoad:
    day: date
    distance_m: float | None = None
    duration_s: float | None = None
    energy_kcal: float | None = None


def bucket_start(day: date, period: str) -> date:
    """First day of the period containing `day`. Weeks start Monday (ISO)."""
    if period == "week":
        return day - timedelta(days=day.weekday())
    if period == "month":
        return day.replace(day=1)
    raise ValueError(f"unsupported period: {period}")


def bucket_end(start: date, period: str) -> date:
    if period == "week":
        return start + timedelta(days=6)
    if period == "month":
        return start.replace(day=monthrange(start.year, start.month)[1])
    raise ValueError(f"unsupported period: {period}")


def _next_bucket(start: date, period: str) -> date:
    return bucket_end(start, period) + timedelta(days=1)


def _mean(values: list[float], ndigits: int = 1) -> float | None:
    return round(sum(values) / len(values), ndigits) if values else None


def _total(values: list[float], scale: float = 1.0, ndigits: int = 2) -> float | None:
    return round(sum(values) * scale, ndigits) if values else None


def summarize(
    nutrition: list[NutritionDay],
    weights: list[WeightPoint],
    workouts: list[WorkoutLoad],
    start_date: date,
    end_date: date,
    period: str = "week",
) -> list[dict]:
    """One row per period between start_date and end_date, newest first.

    Nutrient averages are per *logged* day, and skip days flagged partial — a
    day synced while still in progress holds a fraction of its real intake, and
    averaging it in would understate every mean. `days_logged` /
    `days_in_period` is what tells you how much of the period the average
    actually covers.
    """
    if start_date > end_date:
        return []

    by_bucket_nutrition: dict[date, list[NutritionDay]] = {}
    by_bucket_weight: dict[date, list[WeightPoint]] = {}
    by_bucket_load: dict[date, list[WorkoutLoad]] = {}

    for row in nutrition:
        if start_date <= row.day <= end_date:
            by_bucket_nutrition.setdefault(bucket_start(row.day, period), []).append(row)
    for point in weights:
        if start_date <= point.day <= end_date:
            by_bucket_weight.setdefault(bucket_start(point.day, period), []).append(point)
    for load in workouts:
        if start_date <= load.day <= end_date:
            by_bucket_load.setdefault(bucket_start(load.day, period), []).append(load)

    out: list[dict] = []
    cursor = bucket_start(start_date, period)
    while cursor <= end_date:
        end = bucket_end(cursor, period)
        # Clamp to the requested window so "5 of 7 days logged" stays honest at
        # the edges, where a partial week is all the caller asked about.
        window_start = max(cursor, start_date)
        window_end = min(end, end_date)

        days = by_bucket_nutrition.get(cursor, [])
        logged = [d for d in days if not d.partial and any(v is not None for v in d.values.values())]
        partial_days = [d for d in days if d.partial]

        averages: dict[str, float | None] = {}
        for col in NUTRIENT_COLUMNS:
            present = [d.values[col] for d in logged if d.values.get(col) is not None]
            averages[col] = _mean([float(v) for v in present])

        points = sorted(by_bucket_weight.get(cursor, []), key=lambda p: p.day)
        weight_avg = _mean([p.weight for p in points], ndigits=2)
        weight_start = round(points[0].weight, 2) if points else None
        weight_end = round(points[-1].weight, 2) if points else None
        weight_change = (
            round(weight_end - weight_start, 2)
            if weight_start is not None and weight_end is not None and len(points) > 1
            else None
        )

        protein = averages.get("protein_g")
        protein_per_kg = (
            round(protein / weight_avg, 2) if protein is not None and weight_avg else None
        )

        loads = by_bucket_load.get(cursor, [])
        out.append(
            {
                "period_start": window_start,
                "period_end": window_end,
                "days_logged": len(logged),
                "days_partial": len(partial_days),
                "days_in_period": (window_end - window_start).days + 1,
                "nutrition": averages,
                "protein_g_per_kg": protein_per_kg,
                "body": {
                    "weight_avg": weight_avg,
                    "weight_start": weight_start,
                    "weight_end": weight_end,
                    "weight_change": weight_change,
                },
                "training": {
                    "workouts": len(loads),
                    "distance_km": _total(
                        [w.distance_m for w in loads if w.distance_m is not None], scale=0.001
                    ),
                    "duration_min": _total(
                        [w.duration_s for w in loads if w.duration_s is not None], scale=1 / 60, ndigits=1
                    ),
                    "energy_kcal": _total(
                        [w.energy_kcal for w in loads if w.energy_kcal is not None], ndigits=0
                    ),
                },
            }
        )
        cursor = _next_bucket(cursor, period)

    # Newest first, matching the other list/summary endpoints.
    out.reverse()
    return out
