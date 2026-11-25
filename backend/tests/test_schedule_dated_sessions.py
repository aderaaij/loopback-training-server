"""Strength sessions on individual dates, next to or instead of a weekly pattern.

An athlete who fits strength around the rest of the week has no fixed gym day,
so a schedule that can only say "every Sunday" puts every session on the wrong
date. These cover the dated sessions, single-week exceptions to a pattern, and
the shape old app builds need to keep decoding the plan.
"""

from datetime import date, timedelta

from app.schedule_utils import normalize_schedule, resolve_sessions

TODAY = date.today()
MONDAY = TODAY + timedelta(days=(7 - TODAY.weekday()) % 7 or 7)  # next Monday
TUE, THU, SAT = (MONDAY + timedelta(days=n) for n in (1, 3, 5))


def make_plan(client, activity="strength"):
    r = client.post(
        "/api/plans",
        json={"name": "Gym", "activityType": activity, "startDate": TODAY.isoformat()},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def add(client, plan_id, day, title="Lower", routine="hevy-1"):
    return client.post(
        f"/api/plans/{plan_id}/schedule/sessions",
        json={"date": day.isoformat(), "title": title, "routineId": routine},
    )


def weekly(client, plan_id, weeks=2):
    return client.put(
        f"/api/plans/{plan_id}/schedule",
        json={
            "startDate": MONDAY.isoformat(),
            "weeks": weeks,
            "days": {"tue": {"title": "Lower", "routineId": "hevy-1"}},
        },
    )


def dates(body):
    return [s["date"] for s in body["sessions"]]


# --- pure expansion ----------------------------------------------------------

def test_resolve_merges_pattern_and_dated_sessions_in_date_order():
    sessions = resolve_sessions({
        "startDate": MONDAY.isoformat(),
        "weeks": 1,
        "days": {"thu": {"title": "Upper"}},
        "sessions": [{"date": TUE.isoformat(), "title": "Lower", "routineId": "r"}],
    })
    assert [(s["date"], s["title"], s["recurring"]) for s in sessions] == [
        (TUE, "Lower", False),
        (THU, "Upper", True),
    ]
    assert sessions[0]["weekday"] == "tue"


def test_resolve_skips_one_occurrence_only():
    sessions = resolve_sessions({
        "startDate": MONDAY.isoformat(),
        "weeks": 3,
        "days": {"tue": {"title": "Lower"}},
        "skipDates": [(TUE + timedelta(days=7)).isoformat()],
    })
    assert [s["date"] for s in sessions] == [TUE, TUE + timedelta(days=14)]


def test_resolve_ignores_a_malformed_dated_session():
    sessions = resolve_sessions({"sessions": [{"date": "soon", "title": "x"}, {"title": "y"}, "nope"]})
    assert sessions == []


def test_normalize_gives_a_dated_only_schedule_the_fields_old_apps_require():
    out = normalize_schedule({
        "sessions": [
            {"date": (TUE + timedelta(days=14)).isoformat(), "title": "Upper"},
            {"date": TUE.isoformat(), "title": "Lower"},
        ],
    })
    assert out["startDate"] == TUE.isoformat()
    assert out["weeks"] == 3
    assert out["days"] == {}
    assert [s["date"] for s in out["sessions"]] == [TUE.isoformat(), (TUE + timedelta(days=14)).isoformat()]
    assert "skipDates" not in out


def test_normalize_returns_none_when_nothing_is_left():
    assert normalize_schedule({"days": {}, "sessions": [], "startDate": TUE.isoformat(), "weeks": 2}) is None


# --- adding ------------------------------------------------------------------

def test_add_session_starts_a_schedule_on_a_plan_without_one(client_a):
    plan_id = make_plan(client_a)

    r = add(client_a, plan_id, THU)

    assert r.status_code == 200, r.text
    body = r.json()
    assert dates(body) == [THU.isoformat()]
    assert body["sessions"][0]["recurring"] is False
    assert body["sessions"][0]["routineId"] == "hevy-1"
    # What iOS builds up to 1.0 (15) need to keep decoding the plan.
    assert body["schedule"]["startDate"] == THU.isoformat()
    assert body["schedule"]["weeks"] == 1
    assert body["schedule"]["days"] == {}


def test_dated_sessions_reach_the_calendar_and_the_plan_progress(client_a):
    plan_id = make_plan(client_a)
    add(client_a, plan_id, TUE)
    add(client_a, plan_id, SAT, title="Upper")

    r = client_a.get("/api/schedule/calendar", params={"from": MONDAY.isoformat(), "to": SAT.isoformat()})
    strength = [e for e in r.json()["entries"] if e["kind"] == "strength"]
    assert [(e["date"], e["title"]) for e in strength] == [(TUE.isoformat(), "Lower"), (SAT.isoformat(), "Upper")]

    plan = client_a.get(f"/api/plans/{plan_id}").json()
    assert plan["progress"]["runs_total"] == 2
    assert plan["metadata"]["schedule"]["days"] == {}


def test_adding_the_same_title_on_the_same_day_replaces_it(client_a):
    plan_id = make_plan(client_a)
    add(client_a, plan_id, TUE, routine="old")

    body = add(client_a, plan_id, TUE, routine="new").json()

    assert len(body["sessions"]) == 1
    assert body["sessions"][0]["routineId"] == "new"


def test_add_session_keeps_the_weekly_pattern(client_a):
    plan_id = make_plan(client_a)
    weekly(client_a, plan_id, weeks=1)

    body = add(client_a, plan_id, SAT, title="Upper").json()

    assert dates(body) == [TUE.isoformat(), SAT.isoformat()]
    assert body["schedule"]["startDate"] == MONDAY.isoformat()
    assert body["schedule"]["weeks"] == 1


def test_put_accepts_dated_sessions_without_a_pattern(client_a):
    plan_id = make_plan(client_a)

    r = client_a.put(
        f"/api/plans/{plan_id}/schedule",
        json={"sessions": [{"date": TUE.isoformat(), "title": "Lower"}]},
    )

    assert r.status_code == 200, r.text
    assert dates(r.json()) == [TUE.isoformat()]


def test_put_rejects_an_empty_schedule_and_a_pattern_without_dates(client_a):
    plan_id = make_plan(client_a)
    assert client_a.put(f"/api/plans/{plan_id}/schedule", json={}).status_code == 422
    assert client_a.put(
        f"/api/plans/{plan_id}/schedule", json={"days": {"tue": {"title": "Lower"}}}
    ).status_code == 422


def test_sessions_are_for_strength_plans_only(client_a):
    plan_id = make_plan(client_a, activity="running")
    assert add(client_a, plan_id, TUE).status_code == 400


# --- removing and moving -----------------------------------------------------

def test_remove_drops_a_dated_session_and_clears_an_emptied_schedule(client_a):
    plan_id = make_plan(client_a)
    add(client_a, plan_id, TUE)

    r = client_a.delete(f"/api/plans/{plan_id}/schedule/sessions/{TUE.isoformat()}")

    assert r.status_code == 200, r.text
    assert r.json()["sessions"] == []
    assert r.json()["schedule"] is None
    assert "schedule" not in client_a.get(f"/api/plans/{plan_id}").json()["metadata"]


def test_remove_skips_one_weekly_occurrence_and_keeps_the_rest(client_a):
    plan_id = make_plan(client_a)
    weekly(client_a, plan_id, weeks=2)

    r = client_a.delete(f"/api/plans/{plan_id}/schedule/sessions/{TUE.isoformat()}")

    assert r.status_code == 200, r.text
    assert dates(r.json()) == [(TUE + timedelta(days=7)).isoformat()]
    assert r.json()["schedule"]["skipDates"] == [TUE.isoformat()]


def test_remove_on_a_day_with_nothing_scheduled_is_404(client_a):
    plan_id = make_plan(client_a)
    weekly(client_a, plan_id)
    assert client_a.delete(f"/api/plans/{plan_id}/schedule/sessions/{THU.isoformat()}").status_code == 404


def test_move_takes_a_weekly_occurrence_to_another_day_for_that_week_only(client_a):
    plan_id = make_plan(client_a)
    weekly(client_a, plan_id, weeks=2)

    r = client_a.post(
        f"/api/plans/{plan_id}/schedule/sessions/{TUE.isoformat()}/move",
        json={"to": THU.isoformat()},
    )

    assert r.status_code == 200, r.text
    sessions = r.json()["sessions"]
    assert [(s["date"], s["title"], s["routineId"], s["recurring"]) for s in sessions] == [
        (THU.isoformat(), "Lower", "hevy-1", False),
        ((TUE + timedelta(days=7)).isoformat(), "Lower", "hevy-1", True),
    ]


def test_move_a_dated_session(client_a):
    plan_id = make_plan(client_a)
    add(client_a, plan_id, TUE)

    r = client_a.post(
        f"/api/plans/{plan_id}/schedule/sessions/{TUE.isoformat()}/move",
        json={"to": SAT.isoformat()},
    )

    assert dates(r.json()) == [SAT.isoformat()]


def test_another_users_plan_is_not_reachable(client_a, client_b):
    plan_id = make_plan(client_a)
    assert add(client_b, plan_id, TUE).status_code == 404
