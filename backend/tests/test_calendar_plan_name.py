"""Calendar run entries must resolve planName from their plan_id.

Bug: build_calendar hardcoded planName=None for runs while strength entries
carried plan.name, so the LLM/dashboard saw every queued run as plan-less
despite a valid planId.
"""

TS = "2026-07-20T08:00:00+00:00"  # a Monday


def make_plan(client, name, **over):
    payload = {"name": name, "activityType": "running", "startDate": "2026-07-20"}
    payload.update(over)
    r = client.post("/api/plans", json=payload)
    assert r.status_code == 201
    return r.json()["id"]


def queue_run(client, plan_id=None, sched=TS):
    r = client.post(
        "/api/queue",
        json={"activityType": "running", "title": "Easy 5K", "scheduledDate": sched, "planId": plan_id},
    )
    assert r.status_code == 201
    return r.json()["id"]


def calendar_entries(client, day="2026-07-20"):
    r = client.get("/api/schedule/calendar", params={"from": day, "to": day})
    assert r.status_code == 200
    return r.json()["entries"]


def test_run_entry_carries_plan_name(client_a):
    plan_id = make_plan(client_a, "Phase 2 – Base Build")
    queue_run(client_a, plan_id=plan_id)

    (run,) = calendar_entries(client_a)
    assert run["kind"] == "run"
    assert run["planId"] == plan_id
    assert run["planName"] == "Phase 2 – Base Build"


def test_run_from_inactive_plan_still_resolves_name(client_a):
    plan_id = make_plan(client_a, "Finished Block")
    queue_run(client_a, plan_id=plan_id)
    assert client_a.patch(f"/api/plans/{plan_id}", json={"status": "completed"}).status_code == 200

    (run,) = calendar_entries(client_a)
    assert run["planName"] == "Finished Block"


def test_planless_run_keeps_null_plan_name(client_a):
    queue_run(client_a)

    (run,) = calendar_entries(client_a)
    assert run["planId"] is None
    assert run["planName"] is None


def test_run_and_strength_both_named(client_a):
    run_plan = make_plan(client_a, "Phase 2 – Base Build")
    queue_run(client_a, plan_id=run_plan, sched="2026-07-21T08:00:00+00:00")
    strength_plan = make_plan(client_a, "Return to Lifting", activityType="strength")
    sched = client_a.put(
        f"/api/plans/{strength_plan}/schedule",
        json={"startDate": "2026-07-20", "weeks": 1, "days": {"mon": {"title": "Upper A"}}},
    )
    assert sched.status_code == 200

    entries = client_a.get(
        "/api/schedule/calendar", params={"from": "2026-07-20", "to": "2026-07-21"}
    ).json()["entries"]
    by_kind = {e["kind"]: e for e in entries}
    assert by_kind["run"]["planName"] == "Phase 2 – Base Build"
    assert by_kind["strength"]["planName"] == "Return to Lifting"


# ── a plan that is someone else's ──

RUN = {"activityType": "running", "title": "Easy 5K", "scheduledDate": TS}


def test_a_run_cannot_be_hung_on_someone_elses_plan(client_a, client_b):
    theirs = make_plan(client_b, "Bob's marathon block")
    unknown = "00000000-0000-4000-8000-000000000000"

    # Someone else's plan and one that does not exist get the same answer, so
    # the reply does not say which ids are real.
    for plan_id in (theirs, unknown):
        assert client_a.post("/api/queue", json={**RUN, "planId": plan_id}).status_code == 404
        assert client_a.post("/api/queue/batch", json=[RUN, {**RUN, "planId": plan_id}]).status_code == 404
        mine = queue_run(client_a)
        assert client_a.patch(f"/api/queue/{mine}", json={"planId": plan_id}).status_code == 404
        assert client_a.delete(f"/api/queue/{mine}").status_code in (200, 204)

    # Nothing was queued by the refused requests, the batch included.
    assert client_a.get("/api/queue").json() == []


def test_the_calendar_names_only_the_athletes_own_plans(client_a, client_b, user_a, session_factory):
    """A row that already points at someone else's plan gives nothing away."""
    from app.models.queue import WorkoutQueue

    theirs = make_plan(client_b, "Bob's marathon block")
    item = queue_run(client_a)
    with session_factory() as db:
        db.get(WorkoutQueue, item).plan_id = theirs
        db.commit()

    (run,) = calendar_entries(client_a)
    assert run["planId"] == theirs
    assert run["planName"] is None
