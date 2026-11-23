"""Whether an open setback looks over, from the recent metrics and the
athlete's own daily status. The rules are pure, so most of this needs no
database; the last tests check the read reaches the API and the coach."""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from app.setback_recovery import assess_recovery

TODAY = date(2026, 11, 26)
START = date(2026, 11, 20)


def row(day, rhr=None, hrv=None, resp=None, temp=None):
    return SimpleNamespace(
        date=day, resting_heart_rate=rhr, hrv_sdnn=hrv, respiratory_rate=resp, wrist_temperature=temp
    )


def checkin(day, status):
    return SimpleNamespace(date=day, status=status)


def baseline(rhr=50.0, hrv=60.0, resp=14.0, days=28):
    """Steady weeks before the setback, with a little day-to-day movement."""
    return [
        row(START - timedelta(days=n), rhr + (n % 3 - 1), hrv + (n % 5 - 2) * 2, resp + (n % 2) * 0.2)
        for n in range(1, days + 1)
    ]


def ill_days(*readings):
    """Readings for the days ending today, oldest first."""
    first = TODAY - timedelta(days=len(readings) - 1)
    return [row(first + timedelta(days=i), *r) for i, r in enumerate(readings)]


def assess(rows, checkins=(), kind="illness"):
    return assess_recovery(kind, START, checkins, rows, TODAY)


def test_numbers_back_in_range_for_two_readings_look_recovered():
    r = assess(baseline() + ill_days((61, 38, 16.5), (51, 58, 14.2), (50, 61, 14.0)))
    assert r.status == "looks_recovered"
    assert r.basis == "metrics"
    assert r.summary.startswith("Resting heart rate 50 bpm (usual 50), HRV 61 ms (usual ")
    assert r.summary.endswith("back in the usual range for the last 2 readings.")
    assert {m.metric: m.state for m in r.metrics} == {
        "resting_heart_rate": "normal",
        "hrv_sdnn": "normal",
        "respiratory_rate": "normal",
    }


def test_one_good_day_is_not_enough():
    r = assess(baseline() + ill_days((62, 36, 16.8), (60, 40, 16.0), (51, 59, 14.1)))
    assert r.status == "not_yet"


def test_a_raised_resting_heart_rate_is_named_with_its_size():
    r = assess(baseline() + ill_days((58, 59, 14.1), (58, 60, 14.0)))
    assert r.status == "not_yet"
    assert "Resting heart rate is still 8 bpm above usual (58 against 50)." in r.summary
    assert "HRV and breathing rate are back in the usual range." in r.summary


def test_only_the_unhealthy_direction_counts():
    """A lower resting heart rate or a higher HRV than usual is not a symptom."""
    r = assess(baseline() + ill_days((42, 85, 12.0), (43, 88, 12.1)))
    assert r.status == "looks_recovered"


def test_a_steady_baseline_still_allows_a_few_beats():
    steady = [row(START - timedelta(days=n), 50, 60, 14.0) for n in range(1, 29)]
    assert assess(steady + ill_days((53, 52, 14.9), (52, 55, 14.5))).status == "looks_recovered"
    assert assess(steady + ill_days((54, 60, 14.0), (54, 60, 14.0))).status == "not_yet"


def test_a_wrist_temperature_still_raised_holds_it_back():
    """Everything else is normal; the nights are still half a degree warm."""
    weeks = [
        row(r.date, r.resting_heart_rate, r.hrv_sdnn, r.respiratory_rate, 35.6 + (i % 3) * 0.1)
        for i, r in enumerate(baseline())
    ]
    warm = assess(weeks + ill_days((50, 60, 14.0, 36.4), (50, 61, 14.0, 36.3)))
    assert warm.status == "not_yet"
    assert "Wrist temperature is still 0.6 °C above usual (36.3 against 35.7)." in warm.summary

    cooled = assess(weeks + ill_days((50, 60, 14.0, 35.9), (50, 61, 14.0, 35.7)))
    assert cooled.status == "looks_recovered"
    assert "wrist temperature 35.7 °C (usual 35.7)" in cooled.summary

    # An athlete whose watch records none is judged on the rest.
    assert [m.metric for m in assess(baseline() + ill_days((50, 60, 14.0), (50, 61, 14.0))).metrics] == [
        "resting_heart_rate", "hrv_sdnn", "respiratory_rate",
    ]


def test_no_usual_or_no_recent_readings_means_no_verdict():
    assert assess(baseline(days=5) + ill_days((50, 60, 14), (50, 60, 14))).status == "insufficient_data"
    assert assess(baseline()).status == "insufficient_data"
    # One comparable metric is not enough to go on.
    only_rhr = [row(r.date, r.resting_heart_rate) for r in baseline()] + ill_days((50,), (50,))
    assert assess(only_rhr).status == "insufficient_data"


def test_readings_from_the_first_day_or_long_ago_do_not_count():
    # Normal readings, but on the day it started and five days back.
    stale = [row(START, 50, 60, 14.0), row(TODAY - timedelta(days=5), 50, 60, 14.0)]
    r = assess(baseline() + stale)
    assert r.status == "insufficient_data"
    assert all(m.state == "no_recent_data" for m in r.metrics)


def test_feeling_no_better_holds_the_suggestion_back():
    rows = baseline() + ill_days((51, 58, 14.2), (50, 61, 14.0))
    r = assess(rows, [checkin(TODAY, "same")])
    assert r.status == "not_yet"
    assert r.basis == "status"
    assert '"same"' in r.summary
    # An old "worse" does not, and neither does a fresh "better".
    assert assess(rows, [checkin(TODAY - timedelta(days=3), "worse")]).status == "looks_recovered"
    assert assess(rows, [checkin(TODAY, "better")]).status == "looks_recovered"


def test_fine_two_days_running_looks_recovered_whatever_the_numbers_say():
    fine = [checkin(TODAY - timedelta(days=1), "fine"), checkin(TODAY, "fine")]
    r = assess(baseline() + ill_days((60, 40, 16), (60, 40, 16)), fine)
    assert (r.status, r.basis) == ("looks_recovered", "status")
    # Not when the two are days apart, or the last one is old.
    gap = [checkin(TODAY - timedelta(days=2), "fine"), checkin(TODAY, "fine")]
    assert assess(baseline() + ill_days((60, 40, 16), (60, 40, 16)), gap).status == "not_yet"


def test_an_injury_goes_by_status_alone():
    rows = baseline() + ill_days((50, 60, 14), (50, 60, 14))
    r = assess(rows, kind="injury")
    assert r.status == "insufficient_data"
    assert r.metrics == []
    fine = [checkin(TODAY - timedelta(days=1), "fine"), checkin(TODAY, "fine")]
    assert assess(rows, fine, kind="injury").status == "looks_recovered"


# ── through the API ─────────────────────────────────────────────────────────

NOW = datetime.now(timezone.utc).date()


def _seed(client, start, recent):
    metrics = [
        {"date": (start - timedelta(days=n)).isoformat(), "restingHeartRate": 50 + n % 3, "hrvSdnn": 60 + n % 4, "respiratoryRate": 14.0}
        for n in range(1, 29)
    ] + [
        {"date": (NOW - timedelta(days=i)).isoformat(), "restingHeartRate": rhr, "hrvSdnn": hrv, "respiratoryRate": 14.0}
        for i, (rhr, hrv) in enumerate(recent)
    ]
    assert client.post("/api/health/metrics", json={"metrics": metrics}).status_code == 200


def test_an_open_illness_carries_its_recovery_read(client_a):
    start = NOW - timedelta(days=5)
    _seed(client_a, start, [(51, 61), (50, 60)])
    s = client_a.post("/api/setbacks", json={"kind": "illness", "startDate": start.isoformat()}).json()
    assert s["recovery"]["status"] == "looks_recovered"
    rhr = next(m for m in s["recovery"]["metrics"] if m["metric"] == "resting_heart_rate")
    assert rhr["state"] == "normal"
    assert rhr["latestDate"] == NOW.isoformat()

    hint = client_a.get("/api/plan-notes/context").json()["setback_hint"]
    assert "it looks over" in hint
    assert "close it only if they say so" in hint

    # Once closed there is nothing left to suggest.
    closed = client_a.patch(f"/api/setbacks/{s['id']}", json={"endDate": NOW.isoformat()}).json()
    assert closed["recovery"] is None


def test_still_off_numbers_reach_the_coach_as_a_recovery_check(client_a):
    start = NOW - timedelta(days=4)
    _seed(client_a, start, [(60, 41), (61, 39)])
    s = client_a.post("/api/setbacks", json={"kind": "illness", "startDate": start.isoformat()}).json()
    assert s["recovery"]["status"] == "not_yet"
    hint = client_a.get("/api/plan-notes/context").json()["setback_hint"]
    assert "Recovery check: Resting heart rate is still" in hint
