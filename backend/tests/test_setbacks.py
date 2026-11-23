"""Setbacks: illness and injury records, their daily check-ins, and how they
reach the coach through the plan context."""

import uuid
from datetime import datetime, timedelta, timezone

SETBACKS = "/api/setbacks"
CONTEXT = "/api/plan-notes/context"
CONSENT = "/api/me/data-consent"
COACH = {"X-Consent-Scope": "coach"}

# The server counts days in UTC.
TODAY = datetime.now(timezone.utc).date()


def day(offset: int) -> str:
    return (TODAY + timedelta(days=offset)).isoformat()


def log(client, kind="illness", start=-3, **extra):
    r = client.post(SETBACKS, json={"kind": kind, "startDate": day(start), **extra})
    assert r.status_code == 201, r.text
    return r.json()


def test_a_new_setback_is_open_and_counts_its_days(client_a):
    s = log(client_a, severity="severe", note="  Flu, fever  ")
    assert s["active"] is True
    assert s["endDate"] is None
    assert s["severity"] == "severe"
    assert s["note"] == "Flu, fever"
    assert s["days"] in (3, 4, 5)  # day 4, give or take the UTC date line
    assert s["checkins"] == []


def test_closing_fixes_the_day_count_and_null_reopens(client_a):
    s = log(client_a, start=-5)
    r = client_a.patch(f"{SETBACKS}/{s['id']}", json={"endDate": day(-2)})
    assert r.status_code == 200, r.text
    assert r.json()["active"] is False
    assert r.json()["days"] == 4

    r = client_a.patch(f"{SETBACKS}/{s['id']}", json={"endDate": None})
    assert r.json()["active"] is True

    # A field that is left out is left alone.
    r = client_a.patch(f"{SETBACKS}/{s['id']}", json={"endDate": day(-1), "note": "cold"})
    r = client_a.patch(f"{SETBACKS}/{s['id']}", json={"severity": "mild"})
    assert r.json()["endDate"] == day(-1)
    assert r.json()["note"] == "cold"


def test_end_before_start_is_refused(client_a):
    r = client_a.post(SETBACKS, json={"kind": "illness", "startDate": day(-1), "endDate": day(-3)})
    assert r.status_code == 422
    s = log(client_a)
    assert client_a.patch(f"{SETBACKS}/{s['id']}", json={"endDate": day(-9)}).status_code == 422


def test_one_open_illness_at_a_time_but_injuries_differ_by_body_part(client_a):
    first = log(client_a)
    r = client_a.post(SETBACKS, json={"kind": "illness", "startDate": day(0)})
    assert r.status_code == 409
    assert first["id"] in r.json()["detail"]

    log(client_a, kind="injury", bodyPart="Left calf")
    log(client_a, kind="injury", bodyPart="Right knee")
    r = client_a.post(SETBACKS, json={"kind": "injury", "startDate": day(0), "bodyPart": "left calf"})
    assert r.status_code == 409

    # A finished one never blocks, and reopening into a duplicate is refused.
    past = client_a.post(SETBACKS, json={"kind": "illness", "startDate": day(-30), "endDate": day(-25)})
    assert past.status_code == 201
    assert client_a.patch(f"{SETBACKS}/{past.json()['id']}", json={"endDate": None}).status_code == 409


def test_create_with_an_id_is_idempotent(client_a, client_b):
    sid = str(uuid.uuid4())
    body = {"id": sid, "kind": "illness", "startDate": day(-2)}
    assert client_a.post(SETBACKS, json=body).status_code == 201
    again = client_a.post(SETBACKS, json={**body, "severity": "mild"})
    assert again.status_code == 200
    assert again.json()["severity"] == "mild"
    assert len(client_a.get(SETBACKS).json()) == 1
    assert client_b.post(SETBACKS, json=body).status_code == 409


def test_checkins_are_one_per_day_in_date_order(client_a):
    s = log(client_a, start=-3)
    url = f"{SETBACKS}/{s['id']}/checkins"
    assert client_a.put(f"{url}/{day(-1)}", json={"status": "better"}).status_code == 200
    assert client_a.put(f"{url}/{day(-2)}", json={"status": "worse", "note": "fever"}).status_code == 200
    r = client_a.put(f"{url}/{day(-1)}", json={"status": "same"})
    assert [(c["date"], c["status"]) for c in r.json()["checkins"]] == [(day(-2), "worse"), (day(-1), "same")]

    # Changing only the status keeps that day's note; an explicit null clears it.
    r = client_a.put(f"{url}/{day(-2)}", json={"status": "same"})
    assert r.json()["checkins"][0]["note"] == "fever"
    r = client_a.put(f"{url}/{day(-2)}", json={"status": "worse", "note": None})
    assert r.json()["checkins"][0]["note"] is None

    assert client_a.put(f"{url}/{day(-9)}", json={"status": "same"}).status_code == 422
    assert client_a.put(f"{url}/{day(-1)}", json={"status": "great"}).status_code == 422

    r = client_a.delete(f"{url}/{day(-2)}")
    assert [c["date"] for c in r.json()["checkins"]] == [day(-1)]


def test_listing_puts_open_ones_first_and_filters(client_a):
    old = client_a.post(SETBACKS, json={"kind": "injury", "startDate": day(-90), "endDate": day(-80)}).json()
    current = log(client_a)
    assert [s["id"] for s in client_a.get(SETBACKS).json()] == [current["id"], old["id"]]
    assert [s["id"] for s in client_a.get(SETBACKS, params={"active": "true"}).json()] == [current["id"]]
    assert [s["id"] for s in client_a.get(SETBACKS, params={"active": "false"}).json()] == [old["id"]]
    assert [s["id"] for s in client_a.get(SETBACKS, params={"since": day(-30)}).json()] == [current["id"]]


def test_setbacks_belong_to_their_athlete(client_a, client_b):
    s = log(client_a)
    assert client_b.get(SETBACKS).json() == []
    assert client_b.get(f"{SETBACKS}/{s['id']}").status_code == 404
    assert client_b.patch(f"{SETBACKS}/{s['id']}", json={"note": "x"}).status_code == 404
    assert client_b.put(f"{SETBACKS}/{s['id']}/checkins/{day(0)}", json={"status": "fine"}).status_code == 404
    assert client_b.delete(f"{SETBACKS}/{s['id']}").status_code == 404


def test_delete_takes_the_checkins_with_it(client_a):
    s = log(client_a)
    client_a.put(f"{SETBACKS}/{s['id']}/checkins/{day(0)}", json={"status": "better"})
    assert client_a.delete(f"{SETBACKS}/{s['id']}").status_code == 204
    assert client_a.get(SETBACKS).json() == []


def test_the_plan_context_carries_open_and_recent_setbacks(client_a):
    empty = client_a.get(CONTEXT).json()
    assert empty["setbacks"] == []
    assert empty["setback_hint"] == ""

    client_a.post(SETBACKS, json={"kind": "illness", "startDate": day(-200), "endDate": day(-190)})
    recent = client_a.post(SETBACKS, json={"kind": "injury", "startDate": day(-12), "endDate": day(-6), "bodyPart": "left calf"}).json()
    current = log(client_a, severity="severe")
    client_a.put(f"{SETBACKS}/{current['id']}/checkins/{day(-1)}", json={"status": "better"})

    ctx = client_a.get(CONTEXT).json()
    assert [s["id"] for s in ctx["setbacks"]] == [current["id"], recent["id"]]
    hint = ctx["setback_hint"]
    assert "open severe illness" in hint
    assert "'better'" in hint
    assert "log_setback_status" in hint
    assert "injury (left calf)" in hint


def test_a_recovered_setback_gets_the_build_back_hint(client_a):
    client_a.post(SETBACKS, json={"kind": "illness", "startDate": day(-6), "endDate": day(-3)})
    hint = client_a.get(CONTEXT).json()["setback_hint"]
    assert "Recovered from a moderate illness" in hint
    assert "builds back gradually" in hint


def test_the_coach_sees_nothing_unless_recovery_is_shared(client_a):
    log(client_a)
    assert client_a.put(CONSENT, json={"domains": ["training", "body"]}).status_code == 200

    assert client_a.get(SETBACKS, headers=COACH).status_code == 403
    ctx = client_a.get(CONTEXT, headers=COACH).json()
    assert ctx["setbacks"] == []
    assert ctx["setback_hint"] == ""

    # The athlete's own app is never filtered.
    assert len(client_a.get(SETBACKS).json()) == 1
    assert len(client_a.get(CONTEXT).json()["setbacks"]) == 1


def test_sick_and_injured_are_accepted_as_missed_run_reasons(client_a):
    for reason in ("sick", "injured"):
        r = client_a.post(
            "/api/workouts/feedback",
            json={
                "id": str(uuid.uuid4()),
                "workoutId": str(uuid.uuid4()),
                "workoutName": "Easy 5K",
                "scheduledDate": "2026-11-20T08:00:00Z",
                "detectedAt": "2026-11-21T08:00:00Z",
                "reason": reason,
                "action": "skip",
                "dismissed": False,
            },
        )
        assert r.status_code == 201, r.text
