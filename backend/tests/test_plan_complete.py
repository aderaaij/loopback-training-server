"""Plan completion: the `finishable` signal and POST /api/plans/{id}/complete.

`finishable` marks an active plan the dashboard should offer the
celebrate-and-wrap-up flow for; the complete endpoint flips status, stamps
metadata.completion, stores feedback as a coach-visible plan note, and reports
whether another plan of the same activity is already active (the "ask your
trainer for the next block" nudge fires when there isn't).
"""

import uuid
from datetime import date, timedelta

TODAY = date.today()


def make_plan(client, name="Base Block", activity="running", start=None, end=None, status=None):
    body = {
        "name": name,
        "activityType": activity,
        "startDate": (start or TODAY - timedelta(days=28)).isoformat(),
    }
    if end is not None:
        body["endDate"] = end.isoformat()
    if status is not None:
        body["status"] = status
    r = client.post("/api/plans", json=body)
    assert r.status_code == 201
    return r.json()["id"]


def add_run(client, plan_id, status="completed", title="Easy 5K"):
    r = client.post(
        "/api/queue",
        json={
            "activityType": "running",
            "title": title,
            "planId": str(plan_id),
            "scheduledDate": (TODAY - timedelta(days=1)).isoformat() + "T08:00:00+00:00",
        },
    )
    assert r.status_code == 201
    qid = r.json()["id"]
    if status != "pending":
        assert client.patch(f"/api/queue/{qid}/status", json={"status": status}).status_code == 200
    return qid


def fetch_plan(client, plan_id):
    r = client.get(f"/api/plans/{plan_id}")
    assert r.status_code == 200
    return r.json()


# ── finishable ──


def test_all_runs_done_is_finishable(client_a):
    pid = make_plan(client_a, end=TODAY)  # ends today, not yet past
    add_run(client_a, pid, "completed")
    add_run(client_a, pid, "skipped")
    plan = fetch_plan(client_a, pid)
    assert plan["finishable"] is True
    assert plan["progress"] == {
        "runs_total": 2,
        "runs_completed": 1,
        "runs_skipped": 1,
        "runs_remaining": 0,
    }


def test_all_runs_done_before_the_end_date_is_not_finishable(client_a):
    """Planned a week at a time: this week's sessions are done, the plan has
    months to go."""
    pid = make_plan(client_a, start=TODAY - timedelta(days=5), end=TODAY + timedelta(weeks=21))
    add_run(client_a, pid, "completed")
    add_run(client_a, pid, "completed")
    plan = fetch_plan(client_a, pid)
    assert plan["progress"]["runs_remaining"] == 0
    assert plan["finishable"] is False


def test_all_runs_done_without_an_end_date_is_finishable(client_a):
    pid = make_plan(client_a)
    add_run(client_a, pid, "completed")
    assert fetch_plan(client_a, pid)["finishable"] is True


def test_pending_run_blocks_finishable(client_a):
    pid = make_plan(client_a, end=TODAY)
    add_run(client_a, pid, "completed")
    add_run(client_a, pid, "pending")
    assert fetch_plan(client_a, pid)["finishable"] is False


def test_fully_skipped_plan_is_not_celebrated(client_a):
    pid = make_plan(client_a, end=TODAY)
    add_run(client_a, pid, "skipped")
    assert fetch_plan(client_a, pid)["finishable"] is False


def test_window_passed_is_finishable_without_runs(client_a):
    pid = make_plan(client_a, end=TODAY - timedelta(days=1))
    assert fetch_plan(client_a, pid)["finishable"] is True


def test_open_ended_running_plan_is_not_finishable(client_a):
    pid = make_plan(client_a)  # no end date, no runs
    assert fetch_plan(client_a, pid)["finishable"] is False


def test_future_plan_is_not_finishable(client_a):
    pid = make_plan(client_a, start=TODAY + timedelta(days=2), end=TODAY + timedelta(days=30))
    add_run(client_a, pid, "completed")
    assert fetch_plan(client_a, pid)["finishable"] is False


def test_list_carries_progress_and_finishable(client_a):
    pid = make_plan(client_a, end=TODAY)
    add_run(client_a, pid, "completed")
    row = next(p for p in client_a.get("/api/plans").json() if p["id"] == pid)
    assert row["finishable"] is True
    assert row["progress"]["runs_completed"] == 1


# ── complete ──


def test_complete_marks_plan_and_stores_feedback_note(client_a):
    pid = make_plan(client_a, end=TODAY)
    add_run(client_a, pid, "completed")

    r = client_a.post(
        f"/api/plans/{pid}/complete",
        json={"feedback": "Loved the progression, long runs felt hard.", "rating": 4},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["plan"]["status"] == "completed"
    assert body["plan"]["finishable"] is False
    completion = body["plan"]["metadata"]["completion"]
    assert completion["completed_on"] == TODAY.isoformat()
    assert completion["rating"] == 4
    assert completion["feedback"].startswith("Loved")

    notes = client_a.get("/api/plan-notes", params={"plan_id": str(pid)}).json()
    assert len(notes) == 1
    assert notes[0]["kind"] == "feedback"
    assert "rated 4/5" in notes[0]["summary"]
    assert notes[0]["body"].startswith("Loved")


def test_complete_without_feedback_writes_no_note(client_a):
    pid = make_plan(client_a, end=TODAY - timedelta(days=1))
    r = client_a.post(f"/api/plans/{pid}/complete", json={})
    assert r.status_code == 200
    assert client_a.get("/api/plan-notes", params={"plan_id": str(pid)}).json() == []


def test_complete_reports_next_plan_of_same_activity(client_a):
    pid = make_plan(client_a, name="Block 1", end=TODAY)
    successor = make_plan(
        client_a, name="Block 2", start=TODAY + timedelta(days=2), end=TODAY + timedelta(days=30)
    )
    make_plan(  # different activity — must not count as the successor
        client_a, name="Lifting", activity="strength", end=TODAY + timedelta(days=30)
    )

    body = client_a.post(f"/api/plans/{pid}/complete", json={}).json()
    assert body["next_plan"]["id"] == successor


def test_complete_reports_no_next_plan_when_none_active(client_a):
    pid = make_plan(client_a, end=TODAY)
    make_plan(client_a, name="Old", end=TODAY - timedelta(days=40), status="completed")
    body = client_a.post(f"/api/plans/{pid}/complete", json={}).json()
    assert body["next_plan"] is None


def test_complete_rejects_non_active_plan(client_a):
    pid = make_plan(client_a, end=TODAY, status="completed")
    r = client_a.post(f"/api/plans/{pid}/complete", json={})
    assert r.status_code == 400


def test_complete_rejects_out_of_range_rating(client_a):
    pid = make_plan(client_a, end=TODAY)
    assert client_a.post(f"/api/plans/{pid}/complete", json={"rating": 6}).status_code == 422


def test_cross_user_cannot_complete(client_a, client_b):
    pid = make_plan(client_a, end=TODAY)
    assert client_b.post(f"/api/plans/{pid}/complete", json={}).status_code == 404
    assert fetch_plan(client_a, pid)["status"] == "active"


def test_strength_plan_progress_counts_scheduled_sessions(client_a):
    """A schedule-only strength plan gets real progress: sessions resolved
    from the recurring schedule, completed by date-matching synced strength
    workouts, past unmatched dates counted as skipped."""
    weekday = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[TODAY.weekday()]
    pid = make_plan(
        client_a,
        name="Lifting",
        activity="strength",
        start=TODAY - timedelta(days=14),
        end=TODAY + timedelta(days=7),
    )
    r = client_a.put(
        f"/api/plans/{pid}/schedule",
        json={
            "startDate": (TODAY - timedelta(days=14)).isoformat(),
            "weeks": 3,
            "days": {weekday: {"title": "Lower", "routineId": "hevy-abc"}},
        },
    )
    assert r.status_code == 200

    # One session per week on TODAY's weekday: TODAY-14, TODAY-7, TODAY.
    # A Hevy-synced workout matches the first; the second passed unmatched.
    r = client_a.post(
        "/api/workouts",
        json={
            "id": str(uuid.uuid4()),
            "activityType": "traditionalStrength",
            "source": "com.hevyapp.hevy",
            "startDate": (TODAY - timedelta(days=14)).isoformat() + "T18:00:00+00:00",
            "endDate": (TODAY - timedelta(days=14)).isoformat() + "T19:00:00+00:00",
            "duration": 3600,
        },
    )
    assert r.status_code == 201

    plan = fetch_plan(client_a, pid)
    assert plan["progress"] == {
        "runs_total": 3,
        "runs_completed": 1,
        "runs_skipped": 1,
        "runs_remaining": 1,
    }
    assert plan["finishable"] is False  # today's session is still remaining


def test_cross_user_runs_do_not_leak_into_progress(client_a, client_b):
    pid_a = make_plan(client_a, end=TODAY)
    add_run(client_a, pid_a, "completed")
    # B has their own plan; A's runs must not show up in B's counts.
    pid_b = make_plan(client_b, end=TODAY)
    assert fetch_plan(client_b, pid_b)["progress"]["runs_total"] == 0
    assert uuid.UUID(pid_a) != uuid.UUID(pid_b)
