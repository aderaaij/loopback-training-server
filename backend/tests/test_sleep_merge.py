"""Unit tests for the pure sleep merge (app/sleep_merge.py).

The scenarios mirror the July 2026 corruption:
- inflation: a full-night `unspecified` overlay summed into core on top of
  staged watch data (10-14 Jul) — must never sum again;
- truncation: a bedtime→midnight fragment clobbering the full night — with
  noon-to-noon windows both halves land on the same attribution date.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.sleep_merge import Sample, attribution_date, derive_night, merge_window, night_window, nights_touched

TZ = ZoneInfo("Europe/Amsterdam")
WATCH = "com.apple.health.watch"
PHONE = "com.apple.health.iphone"


def ts(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 7, day, hour, minute, tzinfo=TZ)


def staged_night() -> list[Sample]:
    """A realistic night: bed 22:00 Jul 1 → up 06:30 Jul 2. 30000s asleep, 600s awake."""
    return [
        Sample(ts(1, 22, 0), ts(1, 23, 30), "core", WATCH),
        Sample(ts(1, 23, 30), ts(2, 0, 15), "deep", WATCH),
        Sample(ts(2, 0, 15), ts(2, 1, 0), "rem", WATCH),
        Sample(ts(2, 1, 0), ts(2, 1, 10), "awake", WATCH),
        Sample(ts(2, 1, 10), ts(2, 6, 30), "core", WATCH),
    ]


def test_full_night_derives_once():
    duration, stages = derive_night(staged_night(), date(2026, 7, 2), TZ)
    assert duration == 30000
    assert stages == {"core": 24600, "deep": 2700, "rem": 2700, "awake": 600}


def test_overlap_never_sums():
    """The 10-14 Jul inflation: a second source spanning the whole night as
    `unspecified` must not add a single second — staged stages win every slice."""
    overlay = Sample(ts(1, 22, 0), ts(2, 6, 30), "unspecified", PHONE)
    duration, stages = derive_night([*staged_night(), overlay], date(2026, 7, 2), TZ)
    assert duration == 30000
    assert stages == {"core": 24600, "deep": 2700, "rem": 2700, "awake": 600}


def test_duplicate_staged_samples_never_sum():
    """The same night present twice (duplicate rows / re-imported data)."""
    duration, stages = derive_night(staged_night() + staged_night(), date(2026, 7, 2), TZ)
    assert duration == 30000
    assert stages["core"] == 24600


def test_in_bed_never_counts():
    in_bed = Sample(ts(1, 21, 45), ts(2, 6, 45), "in_bed", PHONE)
    duration, stages = derive_night([*staged_night(), in_bed], date(2026, 7, 2), TZ)
    assert duration == 30000
    assert derive_night([in_bed], date(2026, 7, 2), TZ) is None


def test_unspecified_fills_gaps_and_folds_to_core():
    """Where no staged data exists, unspecified time still counts as sleep,
    reported under core (the shape the app always used for unstaged sleep)."""
    samples = [
        Sample(ts(1, 23, 0), ts(2, 1, 0), "unspecified", PHONE),
        Sample(ts(2, 1, 0), ts(2, 2, 0), "rem", WATCH),
    ]
    duration, stages = derive_night(samples, date(2026, 7, 2), TZ)
    assert duration == 3 * 3600
    assert stages == {"rem": 3600, "core": 7200}


def test_awake_reported_but_not_counted():
    samples = [Sample(ts(2, 2, 0), ts(2, 3, 0), "awake", WATCH), Sample(ts(2, 3, 0), ts(2, 4, 0), "core", WATCH)]
    duration, stages = derive_night(samples, date(2026, 7, 2), TZ)
    assert duration == 3600
    assert stages["awake"] == 3600


def test_gap_produces_no_phantom_time():
    samples = [
        Sample(ts(1, 22, 0), ts(1, 23, 0), "core", WATCH),
        Sample(ts(2, 5, 0), ts(2, 6, 0), "core", WATCH),
    ]
    duration, _ = derive_night(samples, date(2026, 7, 2), TZ)
    assert duration == 7200


def test_noon_attribution_keeps_night_whole():
    """A pre-midnight bedtime no longer bisects the night across two dates."""
    assert attribution_date(ts(1, 22, 0), TZ) == date(2026, 7, 2)
    assert attribution_date(ts(2, 6, 30), TZ) == date(2026, 7, 2)
    assert attribution_date(ts(2, 12, 0), TZ) == date(2026, 7, 3)  # noon boundary is exclusive
    assert derive_night(staged_night(), date(2026, 7, 1), TZ) is None


def test_window_clipping_counts_straddling_sample_once():
    """A sample straddling noon splits across two nights with no double count."""
    nap = Sample(ts(2, 11, 30), ts(2, 12, 30), "core", WATCH)
    d2 = derive_night([nap], date(2026, 7, 2), TZ)
    d3 = derive_night([nap], date(2026, 7, 3), TZ)
    assert d2[0] == 1800 and d3[0] == 1800


def test_nights_touched_spans_windows():
    assert nights_touched(staged_night(), TZ) == {date(2026, 7, 2)}
    long_span = Sample(ts(1, 11, 0), ts(2, 13, 0), "unspecified", PHONE)
    assert nights_touched([long_span], TZ) == {date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3)}
    ends_at_noon = Sample(ts(1, 22, 0), ts(2, 12, 0), "core", WATCH)
    assert nights_touched([ends_at_noon], TZ) == {date(2026, 7, 2)}


def test_two_staged_sources_deterministic_no_sum():
    """Two staged sources disagreeing on a slice: one winner, stable outcome."""
    a = Sample(ts(2, 1, 0), ts(2, 2, 0), "core", WATCH)
    b = Sample(ts(2, 1, 0), ts(2, 2, 0), "deep", PHONE)
    first = merge_window([a, b], *night_window(date(2026, 7, 2), TZ))
    second = merge_window([b, a], *night_window(date(2026, 7, 2), TZ))
    assert first == second
    assert sum(first.values()) == 3600


def test_merge_window_ignores_outside_samples():
    win_start, win_end = night_window(date(2026, 7, 2), TZ)
    outside = Sample(ts(2, 13, 0), ts(2, 14, 0), "core", WATCH)
    assert merge_window([outside], win_start, win_end) == {}


def test_dst_fall_back_night_counts_wall_clock_extra_hour():
    """Sleeping through the Oct fall-back gains a real hour — merge counts
    absolute time, so 22:00→06:30 that night is 9.5h, not 8.5h."""
    samples = [
        Sample(
            datetime(2026, 10, 24, 22, 0, tzinfo=TZ),
            datetime(2026, 10, 25, 6, 30, tzinfo=TZ),
            "unspecified",
            PHONE,
        )
    ]
    duration, _ = derive_night(samples, date(2026, 10, 25), TZ)
    assert duration == 9.5 * 3600
