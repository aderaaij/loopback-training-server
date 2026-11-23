"""Does an open setback look over, going by the most recent data?

A suggestion, never a decision: the athlete closes a setback, and the app and
the coach only ask. Two signals feed it.

**The daily metrics** (illness only). Each of resting heart rate, HRV,
breathing rate and sleeping wrist temperature is compared with the athlete's own values from the four weeks
before the setback started. A metric counts as back to normal when its two
most recent readings are both on the healthy side of `usual ± tolerance`,
where usual is the median of those weeks and tolerance is their standard
deviation, with a floor so a very steady baseline does not make one beat a
deviation. Only the unhealthy direction counts: a resting heart rate below
usual is not a symptom. At least two metrics must be comparable, and all of
them must be back, before the illness "looks recovered".

For an injury these numbers say little, so they are not consulted.

**The athlete's own daily status** (any kind). "Fine" on two days in a row
looks recovered whatever the numbers say; a fresh "worse" or "same" holds the
suggestion back even when the numbers are normal.

Everything here is pure: the route loads the rows and passes them in.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median, pstdev
from typing import Iterable, Protocol

from app.schemas.setback import RecoveryMetricOut, RecoveryOut

# Days before the setback that make up "usual".
BASELINE_DAYS = 28
# Fewer readings than this and there is no usual to compare with.
MIN_BASELINE_READINGS = 7
# Readings that must be back in range, most recent first.
NORMAL_READINGS = 2
# How far back a reading still counts as recent.
RECENT_DAYS = 3
# Comparable metrics needed before the numbers alone can suggest anything.
MIN_METRICS = 2


@dataclass(frozen=True)
class _Metric:
    field: str
    label: str
    unit: str
    higher_is_worse: bool
    # Smallest tolerance, absolute or as a share of the usual value.
    floor: float = 0.0
    relative_floor: float = 0.0
    decimals: int = 0


METRICS: tuple[_Metric, ...] = (
    _Metric("resting_heart_rate", "Resting heart rate", "bpm", higher_is_worse=True, floor=3.0),
    _Metric("hrv_sdnn", "HRV", "ms", higher_is_worse=False, relative_floor=0.15),
    _Metric("respiratory_rate", "Breathing rate", "breaths/min", higher_is_worse=True, floor=1.0, decimals=1),
    # Nights vary by a few tenths on their own; a fever shows as half a degree
    # or more.
    _Metric("wrist_temperature", "Wrist temperature", "°C", higher_is_worse=True, floor=0.3, decimals=1),
)


class _Row(Protocol):
    date: date


class _Checkin(Protocol):
    date: date
    status: str


def baseline_window(start: date) -> tuple[date, date]:
    """First and last day of the weeks a setback is compared with."""
    return start - timedelta(days=BASELINE_DAYS), start - timedelta(days=1)


def _fmt(value: float, metric: _Metric) -> str:
    return f"{value:.{metric.decimals}f}"


def _assess_metric(metric: _Metric, rows: list[_Row], start: date, today: date) -> RecoveryMetricOut | None:
    """One metric against its own baseline; None when it has no baseline."""
    first, last = baseline_window(start)
    readings = [(r.date, getattr(r, metric.field)) for r in rows if getattr(r, metric.field) is not None]
    before = [v for d, v in readings if first <= d <= last]
    if len(before) < MIN_BASELINE_READINGS:
        return None

    usual = median(before)
    tolerance = max(pstdev(before), metric.floor, metric.relative_floor * usual)
    recent = sorted(
        ((d, v) for d, v in readings if d > start and d >= today - timedelta(days=RECENT_DAYS)),
        key=lambda pair: pair[0],
    )[-NORMAL_READINGS:]

    def off_by(value: float) -> float:
        """How far past the tolerance, in the unhealthy direction; 0 inside."""
        gap = (value - usual) if metric.higher_is_worse else (usual - value)
        return max(gap - tolerance, 0.0)

    if len(recent) < NORMAL_READINGS:
        state = "no_recent_data"
    elif all(off_by(v) == 0 for _, v in recent):
        state = "normal"
    else:
        state = "off"

    latest_day, latest = recent[-1] if recent else (None, None)
    return RecoveryMetricOut(
        metric=metric.field,
        label=metric.label,
        unit=metric.unit,
        usual=round(usual, 1),
        tolerance=round(tolerance, 1),
        latest=None if latest is None else round(latest, 1),
        latest_date=latest_day,
        difference=None if latest is None else round(latest - usual, 1),
        state=state,
    )


def _sentence_off(m: RecoveryMetricOut, metric: _Metric) -> str:
    direction = "above" if metric.higher_is_worse else "below"
    return (
        f"{m.label} is still {_fmt(abs(m.difference), metric)} {m.unit} {direction} usual "
        f"({_fmt(m.latest, metric)} against {_fmt(m.usual, metric)})."
    )


def _mid(label: str) -> str:
    """A label as it reads in the middle of a sentence."""
    return label if label.isupper() else label[0].lower() + label[1:]


def _join(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def assess_recovery(
    kind: str,
    start: date,
    checkins: Iterable[_Checkin],
    metric_rows: Iterable[_Row],
    today: date,
) -> RecoveryOut:
    """The recovery read for one open setback.

    `metric_rows` are the athlete's daily-metrics rows from the start of the
    baseline window on; rows outside the windows used are ignored.
    """
    by_field = {m.field: m for m in METRICS}
    rows = list(metric_rows)
    days = sorted(checkins, key=lambda c: c.date)

    assessed: list[RecoveryMetricOut] = []
    if kind == "illness":
        assessed = [a for m in METRICS if (a := _assess_metric(m, rows, start, today)) is not None]
    comparable = [a for a in assessed if a.state in ("normal", "off")]
    off = [a for a in comparable if a.state == "off"]
    normal = [a for a in comparable if a.state == "normal"]

    # The athlete's own word comes first, in both directions.
    last_two = days[-2:]
    if (
        len(last_two) == 2
        and all(c.status == "fine" for c in last_two)
        and last_two[1].date >= today - timedelta(days=1)
        and (last_two[1].date - last_two[0].date).days == 1
    ):
        return RecoveryOut(
            status="looks_recovered", basis="status", summary="Felt fine two days in a row.", metrics=assessed
        )

    fresh = days[-1] if days and days[-1].date >= today - timedelta(days=1) else None
    still_unwell = fresh is not None and fresh.status in ("worse", "same")

    if len(comparable) < MIN_METRICS:
        return RecoveryOut(
            status="insufficient_data",
            basis=None,
            summary="Not enough recent data to compare with the weeks before.",
            metrics=assessed,
        )

    if off:
        parts = [_sentence_off(a, by_field[a.metric]) for a in off]
        if normal:
            names = _join([a.label if i == 0 else _mid(a.label) for i, a in enumerate(normal)])
            parts.append(f"{names} {'is' if len(normal) == 1 else 'are'} back in the usual range.")
        return RecoveryOut(status="not_yet", basis="metrics", summary=" ".join(parts), metrics=assessed)

    readings = _join(
        [
            f"{_mid(a.label)} {_fmt(a.latest, by_field[a.metric])} {a.unit} (usual {_fmt(a.usual, by_field[a.metric])})"
            for a in normal
        ]
    )
    readings = readings[0].upper() + readings[1:]
    if still_unwell:
        return RecoveryOut(
            status="not_yet",
            basis="status",
            summary=f"The numbers are back in the usual range, but the last status was \"{fresh.status}\". {readings}.",
            metrics=assessed,
        )
    return RecoveryOut(
        status="looks_recovered",
        basis="metrics",
        summary=f"{readings}: back in the usual range for the last {NORMAL_READINGS} readings.",
        metrics=assessed,
    )
