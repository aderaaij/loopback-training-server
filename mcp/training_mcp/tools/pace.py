"""MCP tool for pace arithmetic: distance, time and pace, and the splits.

Pure calculation. It reads nothing about the athlete and calls no backend, so
it is available whatever they share. It exists because a model working these
numbers out itself slips: a half marathon becomes 21 km, 1:45:00 becomes 6500
seconds, a split table drifts by a few seconds per row. The iOS app has the
same calculator (`PaceCalculator.swift`); keep the two agreeing.
"""

import logging
import math
from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import Field

from training_mcp.wire import text_result

logger = logging.getLogger(__name__)

pace_router = FastMCP(name="Pace Tools")

Race = Literal["5k", "10k", "half_marathon", "marathon"]
Units = Literal["metric", "imperial"]
Splits = Literal["all", "checkpoints", "none"]

RACE_METERS: dict[str, float] = {
    "5k": 5_000.0,
    "10k": 10_000.0,
    "half_marathon": 21_097.5,
    "marathon": 42_195.0,
}

METERS_PER_MILE = 1609.344

# The marks a race clock is usually read at, besides every km or mile.
CHECKPOINTS: tuple[tuple[str, float], ...] = (
    ("5K", 5_000.0),
    ("10K", 10_000.0),
    ("Half", 21_097.5),
    ("30K", 30_000.0),
)

# Beyond this many kilometers or miles a row for each is a list nobody reads.
MAX_UNIT_ROWS = 200


def parse_clock(value: str | float, what: str) -> float:
    """Seconds from "H:MM:SS", "MM:SS" or a bare number of seconds."""
    if isinstance(value, (int, float)):
        seconds = float(value)
    else:
        parts = value.strip().split(":")
        if not 1 <= len(parts) <= 3 or any(p.strip() == "" for p in parts):
            raise ValueError(f'{what} "{value}" is not H:MM:SS, MM:SS or a number of seconds')
        try:
            numbers = [float(p) for p in parts]
        except ValueError:
            raise ValueError(f'{what} "{value}" is not H:MM:SS, MM:SS or a number of seconds') from None
        if any(n < 0 for n in numbers):
            raise ValueError(f"{what} cannot be negative")
        # 4:75 is a slip, not 5:15.
        if any(n >= 60 for n in numbers[1:]):
            raise ValueError(f'{what} "{value}" has minutes or seconds of 60 or more')
        seconds = 0.0
        for n in numbers:
            seconds = seconds * 60 + n
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError(f"{what} must be above zero")
    return seconds


def clock(seconds: float) -> str:
    """ "24:51" under an hour, "1:45:00" from there on. Rounded to the second."""
    total = int(seconds + 0.5)
    hours, minutes, secs = total // 3600, total % 3600 // 60, total % 60
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _trimmed(value: float, decimals: int) -> str:
    """At most `decimals` places, no trailing zeros: "10", "21.1", "42.2"."""
    # The nudge is for 42.195, which is stored a hair under and would print
    # as 42.19.
    text = f"{value + 1e-9:.{decimals}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def split_table(meters: float, seconds: float, unit_meters: float, unit: str, every_unit: bool) -> list[dict]:
    """Time at each whole unit, the named checkpoints and the finish.

    Marks on the same spot share a row, so 5 km is also the 5K row and a 10 km
    race ends on a row that is both. Even pace throughout.
    """

    def key(m: float) -> int:
        # Marks within half a meter of each other are the same mark.
        return int(m * 2 + 0.5)

    finish = key(meters)
    positions: dict[int, float] = {finish: meters}
    units: dict[int, int] = {}
    names: dict[int, str] = {}

    whole = int(meters / unit_meters + 1e-9)
    if every_unit and 0 < whole <= MAX_UNIT_ROWS:
        for count in range(1, whole + 1):
            at = count * unit_meters
            units[key(at)] = count
            positions[key(at)] = at
    for label, at in CHECKPOINTS:
        if key(at) <= finish:
            names[key(at)] = label
            positions[key(at)] = at

    rows = []
    for mark in sorted(positions):
        at = positions[mark]
        if mark in units:
            label = f"{units[mark]} {unit}"
        elif mark == finish:
            label = "Finish"
        else:
            label = names[mark]
        row: dict = {"mark": label, "time": clock(seconds * at / meters)}
        if mark in names and label != names[mark]:
            row["checkpoint"] = names[mark]
        if mark == finish and label != "Finish":
            row["finish"] = True
        if mark not in units:
            row["distance_m"] = round(at, 1)
        rows.append(row)
    return rows


@pace_router.tool
@text_result
def calculate_pace(
    race: Annotated[
        Race | None,
        Field(description='A standard race distance, exact to the meter. Use this OR distance_m, not both.'),
    ] = None,
    distance_m: Annotated[
        float | None,
        Field(description="Distance in METERS, for anything that is not one of the standard races."),
    ] = None,
    time: Annotated[
        str | float | None,
        Field(description='Total time as "H:MM:SS" or "MM:SS" ("1:45:00", "24:30"), or a number of seconds.'),
    ] = None,
    pace: Annotated[
        str | float | None,
        Field(
            description='Pace as "M:SS" per kilometer, or per MILE when units is "imperial" '
            '("4:58"), or a number of seconds per that unit.'
        ),
    ] = None,
    units: Annotated[
        Units,
        Field(
            description="The athlete's `units` from get_plan_context. Decides whether `pace` "
            "is read per km or per mile, and whether splits are per km or per mile."
        ),
    ] = "metric",
    splits: Annotated[
        Splits,
        Field(
            description='"all" = every km or mile plus the checkpoints and the finish; '
            '"checkpoints" = only 5K, 10K, half, 30K and the finish; "none" = no table.'
        ),
    ] = "all",
) -> dict:
    """
    Work out a pace, a finish time or a distance from the other two, with the
    split times along the way.

    USE THIS FOR EVERY SUCH NUMBER YOU QUOTE: a target pace for a goal time,
    the finish time a pace gives, the clock at each kilometer of a race, the
    speed for a pace alert. Do not do this arithmetic yourself; it is where
    slips happen (a half marathon is 21.0975 km, not 21).

    Give exactly two of the three: a distance (`race` or `distance_m`), a
    `time`, a `pace`. The third is worked out.

    This converts between numbers. It does not say whether a pace is
    realistic for the athlete; judge that from their training
    (get_recent_runs, get_training_summary) and the coaching playbook.

    Returns:
        - solved_for: "pace", "time" or "distance", whichever was left out.
        - distance_m, and distance in the athlete's unit ("21.1 km").
        - time ("1:45:00") and time_s.
        - pace_per_km and pace_per_mile ("4:59", "8:01"), each rounded to the
          second, with pace_per_km_s and pace_per_mile_s to one decimal.
          Quote the one matching the athlete's units.
        - speed_mps: the same pace as meters per second, the form a workout's
          speed alert takes (create_workout).
        - splits: one row per mark in running order, `mark` ("5 km", "Half",
          "Finish") and the `time` on the clock there at an even pace. A whole
          km or mile that is also a named checkpoint carries `checkpoint`
          ("5K"); one that is the finish carries `finish: true`. Marks between
          two whole units carry `distance_m`. Split times are computed from
          the exact pace, so they add up to the finish time even where the
          rounded pace would not.
        On bad input: {"error": "..."} saying what to change.
    """
    try:
        if race is not None and distance_m is not None:
            return {"error": "Give race or distance_m, not both."}
        meters = RACE_METERS[race] if race is not None else distance_m
        given = [meters is not None, time is not None, pace is not None]
        if sum(given) != 2:
            return {
                "error": "Give exactly two of: a distance (race or distance_m), time, pace. "
                f"Got {sum(given)}."
            }
        if meters is not None and (not math.isfinite(meters) or meters <= 0):
            return {"error": "distance_m must be above zero."}

        unit_meters = METERS_PER_MILE if units == "imperial" else 1000.0
        unit = "mi" if units == "imperial" else "km"
        seconds = parse_clock(time, "time") if time is not None else None
        # Pace arrives per the athlete's unit and is kept per km.
        per_km = parse_clock(pace, "pace") * 1000.0 / unit_meters if pace is not None else None

        if per_km is None:
            solved_for = "pace"
            per_km = seconds / (meters / 1000.0)
        elif seconds is None:
            solved_for = "time"
            seconds = per_km * meters / 1000.0
        else:
            solved_for = "distance"
            meters = seconds / per_km * 1000.0

        per_mile = per_km * METERS_PER_MILE / 1000.0
        result: dict = {
            "solved_for": solved_for,
            "distance_m": round(meters, 1),
            "distance": f"{_trimmed(meters / unit_meters, 2)} {unit}",
            "time": clock(seconds),
            "time_s": round(seconds, 1),
            "pace_per_km": clock(per_km),
            "pace_per_km_s": round(per_km, 1),
            "pace_per_mile": clock(per_mile),
            "pace_per_mile_s": round(per_mile, 1),
            "speed_mps": round(1000.0 / per_km, 3),
        }
        if splits != "none":
            result["splits"] = split_table(meters, seconds, unit_meters, unit, every_unit=splits == "all")
        return result
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        logger.exception(f"Error in calculate_pace: {e}")
        return {"error": str(e)}
