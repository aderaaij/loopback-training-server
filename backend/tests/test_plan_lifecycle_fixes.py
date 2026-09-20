"""Regressions around plan status, schedules and the ramp baseline.

Grouped because they share one theme: a plan built *ahead* of its start date,
and the ways that used to silently drop sessions, warnings or edits. Every case
here failed before the fix, and several failed invisibly — a check that finds
nothing looks exactly like a check that passed.
"""

from datetime import date, timedelta

from app.plan_validation import HistoryRun, PlannedSession, validate_schedule

TODAY = date.today()
NEXT_MONDAY = TODAY + timedelta(days=(7 - TODAY.weekday()) % 7 or 7)


def make_plan(client, name="Block", activity="running", start=None, end=None, status=None):
    body = {
        "name": name,
        "activityType": activity,
        "startDate": (start or TODAY).isoformat(),
    }
    if end is not None:
        body["endDate"] = end.isoformat()
    if status is not None:
        body["status"] = status
    r = client.post("/api/plans", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def set_schedule(client, plan_id, start, weeks=2):
    return client.put(
        f"/api/plans/{plan_id}/schedule",
        json={
            "startDate": start.isoformat(),
            "weeks": weeks,
            "days": {"tue": {"title": "Lower", "routineId": "hevy-1"}},
        },
    )


# --- an upcoming plan's sessions are still real ------------------------------

def test_upcoming_plan_sessions_appear_in_calendar(client_a):
    """`upcoming` means "not the plan I'm on", not "ignore its sessions".

    Filtering the calendar to `active` removed a future block's strength days
    entirely, so conflict detection on the very block being planned silently
    passed.
    """
    start = TODAY + timedelta(days=14)
    plan = make_plan(client_a, "Future Strength", "strength", start=start, status="upcoming")
    assert set_schedule(client_a, plan["id"], start).status_code == 200

    r = client_a.get("/api/schedule/calendar", params={
        "from": start.isoformat(), "to": (start + timedelta(days=14)).isoformat(),
    })
    assert r.status_code == 200
    strength = [e for e in r.json()["entries"] if e["kind"] == "strength"]
    assert strength, "upcoming plan's strength sessions must still be on the calendar"
    assert strength[0]["planName"] == "Future Strength"


def test_calendar_strength_entry_carries_session_type_not_plan_type(client_a):
    """activityType came from the plan row, so it could disagree with the
    `completed` matching in the same dict (which uses traditionalStrength)."""
    start = TODAY + timedelta(days=7)
    plan = make_plan(client_a, "S", "strength", start=start, status="upcoming")
    set_schedule(client_a, plan["id"], start)

    r = client_a.get("/api/schedule/calendar", params={
        "from": start.isoformat(), "to": (start + timedelta(days=7)).isoformat(),
    })
    strength = [e for e in r.json()["entries"] if e["kind"] == "strength"]
    assert strength and strength[0]["activityType"] == "traditionalStrength"


def test_next_plan_finds_an_upcoming_block(client_a):
    """Completing a plan nudged "go plan the next block" even when the next
    block was already built — because it was `upcoming`, not `active`."""
    current = make_plan(client_a, "Now", start=TODAY - timedelta(days=30), end=TODAY)
    make_plan(client_a, "Next", start=TODAY + timedelta(days=14), status="upcoming")

    r = client_a.post(f"/api/plans/{current['id']}/complete", json={})
    assert r.status_code == 200, r.text
    assert r.json()["next_plan"] is not None
    assert r.json()["next_plan"]["name"] == "Next"


# --- schedules belong on strength plans --------------------------------------

def test_schedule_rejected_on_a_running_plan(client_a):
    plan = make_plan(client_a, "Run Block", "running")
    r = set_schedule(client_a, plan["id"], TODAY)
    assert r.status_code == 400
    assert "strength" in r.json()["detail"]


def test_schedule_allowed_on_a_strength_plan(client_a):
    plan = make_plan(client_a, "Gym", "strength")
    assert set_schedule(client_a, plan["id"], TODAY).status_code == 200


# --- write responses carry computed fields -----------------------------------

def test_create_and_update_responses_compute_progress(client_a):
    """`finishable: false` on a write response was a plausible-looking lie —
    `get` on the same plan in the same second could say true."""
    created = make_plan(client_a, "P")
    assert created["progress"] is not None
    assert created["progress"]["runs_total"] == 0

    updated = client_a.patch(f"/api/plans/{created['id']}", json={"name": "P2"}).json()
    fetched = client_a.get(f"/api/plans/{created['id']}").json()
    assert updated["progress"] == fetched["progress"]
    assert updated["finishable"] == fetched["finishable"]


# --- ramp baseline: layoff weeks ---------------------------------------------

def _planned(week_start, km, n=3):
    return [
        PlannedSession(
            date=week_start + timedelta(days=i * 2),
            title=f"Run {i}",
            distance_m=km / n * 1000,
            duration_s=km / n * 330,
            hard=False,
        )
        for i in range(n)
    ]


def _history(km_per_week, anchor):
    """km_per_week newest-last; a 0.0 entry means a week with no running."""
    out = []
    for i, km in enumerate(reversed(km_per_week)):
        monday = anchor - timedelta(weeks=i + 1)
        if km <= 0:
            continue
        for j in range(3):
            out.append(HistoryRun(
                date=monday + timedelta(days=j * 2),
                distance_m=km / 3 * 1000,
                duration_s=km / 3 * 330,
            ))
    return out


def test_layoff_in_baseline_caps_ramp_severity_and_reports_the_weeks():
    """A vacation inside the 4-week window drags the baseline down and inflates
    every ratio against it. The warning still fires — but not as a `critical`
    the athlete could only satisfy by detraining, and it now names the empty
    weeks so the number can be checked."""
    warnings, _ = validate_schedule(
        _planned(NEXT_MONDAY, 19.0),
        _history([17.6, 17.6, 17.1, 0.0], NEXT_MONDAY),
        today=TODAY,
    )
    ramp = [w for w in warnings if w["code"] == "ramp_rate"]
    assert ramp, "a fast ramp off a layoff-depressed baseline should still warn"
    assert ramp[0]["severity"] == "warn"
    weeks = ramp[0]["data"]["baseline_weeks"]
    assert len(weeks) == 4
    assert any(w["km"] == 0.0 for w in weeks), "the empty week must be visible in the payload"
    assert "no running" in ramp[0]["message"]


def test_dense_baseline_still_criticals():
    """The cap is specific to a degenerate window — a genuinely reckless ramp
    off four solid weeks keeps its `critical`."""
    warnings, _ = validate_schedule(
        _planned(NEXT_MONDAY, 40.0),
        _history([15.0, 15.0, 15.0, 15.0], NEXT_MONDAY),
        today=TODAY,
    )
    ramp = [w for w in warnings if w["code"] == "ramp_rate"]
    assert ramp and ramp[0]["severity"] == "critical"
    assert all(w["km"] > 0 for w in ramp[0]["data"]["baseline_weeks"])
