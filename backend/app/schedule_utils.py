"""Pure helpers for expanding a recurring weekly schedule into dated sessions.

The schedule lives on ``plan.metadata["schedule"]`` (see schemas.PlanSchedule)
and is stored with camelCase keys, matching how the API speaks to the app.
"""

from datetime import date, datetime, timedelta

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
WEEKDAY_INDEX = {d: i for i, d in enumerate(WEEKDAYS)}


def _as_date(value) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def resolve_sessions(schedule: dict | None) -> list[dict]:
    """Expand a stored schedule into concrete dated sessions.

    A schedule has two parts, either of which may be absent:

    - a weekly pattern (``startDate``, ``weeks``, ``days``). Weeks are anchored
      to the Monday of the week containing ``startDate``; occurrences before
      ``startDate`` (in week 0) are dropped, and so is any occurrence on a date
      listed in ``skipDates`` (one week's session taken out or moved).
    - individual ``sessions``, each on its own date, for an athlete who fits
      strength around the rest of the week instead of keeping fixed days.

    Returns a list of ``{date, weekday, title, routineId, recurring}`` dicts
    sorted by date; ``recurring`` tells a pattern occurrence from an
    individual session.
    """
    if not schedule:
        return []
    sessions: list[dict] = []

    start = _as_date(schedule.get("startDate"))
    try:
        weeks = int(schedule.get("weeks") or 0)
    except (TypeError, ValueError):
        weeks = 0
    days = schedule.get("days") or {}
    skipped = {d for d in (_as_date(v) for v in schedule.get("skipDates") or []) if d is not None}

    if start is not None and weeks >= 1 and days:
        anchor_monday = start - timedelta(days=start.weekday())
        for week in range(weeks):
            week_monday = anchor_monday + timedelta(days=7 * week)
            for weekday, ref in days.items():
                idx = WEEKDAY_INDEX.get(weekday)
                if idx is None:
                    continue
                day = week_monday + timedelta(days=idx)
                if day < start or day in skipped:
                    continue
                ref = ref or {}
                sessions.append({
                    "date": day,
                    "weekday": weekday,
                    "title": ref.get("title") or weekday.capitalize(),
                    "routineId": ref.get("routineId"),
                    "recurring": True,
                })

    for extra in schedule.get("sessions") or []:
        if not isinstance(extra, dict):
            continue
        day = _as_date(extra.get("date"))
        if day is None:
            continue
        sessions.append({
            "date": day,
            "weekday": WEEKDAYS[day.weekday()],
            "title": extra.get("title") or "Strength",
            "routineId": extra.get("routineId"),
            "recurring": False,
        })

    sessions.sort(key=lambda s: s["date"])
    return sessions


def normalize_schedule(schedule: dict) -> dict | None:
    """Tidy a schedule for storage; None when nothing is left to schedule.

    ``startDate``, ``weeks`` and ``days`` are always written, even for a
    schedule made only of individual sessions: iOS builds up to 1.0 (15)
    decode all three as required and drop the whole plan without them. With no
    weekly pattern they are derived from the sessions, so "start" and "length"
    still describe the cycle.
    """
    out = dict(schedule)
    days = out.get("days") or {}

    dated: dict[tuple[str, str], dict] = {}
    for extra in out.get("sessions") or []:
        day = _as_date(extra.get("date")) if isinstance(extra, dict) else None
        if day is None:
            continue
        entry = {"date": day.isoformat(), "title": extra.get("title") or "Strength"}
        if extra.get("routineId"):
            entry["routineId"] = extra["routineId"]
        # One session per day and title; a repeat replaces the earlier one.
        dated[(entry["date"], entry["title"])] = entry
    sessions = sorted(dated.values(), key=lambda e: (e["date"], e["title"]))

    if not days and not sessions:
        return None

    out["days"] = days
    if days:
        skips = sorted({d.isoformat() for d in (_as_date(v) for v in out.get("skipDates") or []) if d is not None})
    else:
        # Nothing recurs, so there is nothing to skip, and the cycle is as
        # long as its sessions.
        skips = []
        first = date.fromisoformat(sessions[0]["date"])
        last = date.fromisoformat(sessions[-1]["date"])
        monday = first - timedelta(days=first.weekday())
        out["startDate"] = first.isoformat()
        out["weeks"] = min(max((last - monday).days // 7 + 1, 1), 52)

    for key, value in (("sessions", sessions), ("skipDates", skips)):
        if value:
            out[key] = value
        else:
            out.pop(key, None)
    return out


def cycle_end_date(schedule: dict | None) -> date | None:
    """The date of the last session in the cycle, or None."""
    sessions = resolve_sessions(schedule)
    return sessions[-1]["date"] if sessions else None


def to_local_date(value) -> date | None:
    """Coerce a datetime/date/ISO-string to a calendar date."""
    if isinstance(value, datetime):
        return value.date()
    return _as_date(value)
