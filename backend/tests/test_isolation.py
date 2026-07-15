"""Two-user isolation invariants — the acceptance gate for Phase 2 tenancy.

Every test creates data as user A and/or B and asserts one user can never see,
mutate, or destroy another's rows.
"""

import uuid

from fastapi.testclient import TestClient

from app.main import app

TS = "2026-07-10T08:00:00+00:00"


# --- payload builders -------------------------------------------------------

def workout_payload(**over):
    p = {"id": str(uuid.uuid4()), "activityType": "running", "startDate": TS, "endDate": TS, "data": {}}
    p.update(over)
    return p


def inventory_item(iid=None, day=10):
    return {
        "id": iid or str(uuid.uuid4()),
        "displayName": "Run",
        "date": {"year": 2026, "month": 7, "day": day, "hour": 8, "minute": 0},
        "complete": False,
    }


def feedback_payload(workout_id, **over):
    p = {
        "id": str(uuid.uuid4()),
        "workoutId": str(workout_id),
        "workoutName": "Missed run",
        "scheduledDate": TS,
        "detectedAt": TS,
        "reason": "tired",
        "action": "skip",
        "dismissed": False,
    }
    p.update(over)
    return p


# --- unauthenticated --------------------------------------------------------

def test_unauthenticated_is_rejected():
    anon = TestClient(app)
    assert anon.get("/api/workouts").status_code in (401, 403)
    assert anon.get("/api/plans").status_code in (401, 403)


def test_bad_token_is_401():
    c = TestClient(app)
    c.headers["Authorization"] = "Bearer not-a-real-token"
    assert c.get("/api/workouts").status_code == 401


# --- workouts ---------------------------------------------------------------

def test_workout_list_and_get_isolation(client_a, client_b):
    wa = workout_payload()
    assert client_a.post("/api/workouts", json=wa).status_code == 201
    wb = workout_payload()
    assert client_b.post("/api/workouts", json=wb).status_code == 201

    a_ids = {w["id"] for w in client_a.get("/api/workouts").json()}
    b_ids = {w["id"] for w in client_b.get("/api/workouts").json()}
    assert a_ids == {wa["id"]}
    assert b_ids == {wb["id"]}

    # B cannot read A's workout by id
    assert client_b.get(f"/api/workouts/{wa['id']}").status_code == 404
    assert client_a.get(f"/api/workouts/{wa['id']}").status_code == 200


def test_workout_delete_cross_user_404(client_a, client_b):
    wa = workout_payload()
    client_a.post("/api/workouts", json=wa)
    assert client_b.delete(f"/api/workouts/{wa['id']}").status_code == 404
    # still there for A
    assert client_a.get(f"/api/workouts/{wa['id']}").status_code == 200


# --- inventory: the destructive-delete hazard -------------------------------

def test_inventory_sync_does_not_wipe_other_user(client_a, client_b):
    ia1, ia2 = inventory_item(day=1), inventory_item(day=2)
    ib1 = inventory_item(day=3)
    assert client_a.put("/api/workouts/inventory", json=[ia1, ia2]).status_code == 200
    assert client_b.put("/api/workouts/inventory", json=[ib1]).status_code == 200

    # A re-syncs a SMALLER snapshot (drops ia2). The notin_() delete must be
    # scoped to A — B's row must survive.
    assert client_a.put("/api/workouts/inventory", json=[ia1]).status_code == 200

    a_ids = {i["id"] for i in client_a.get("/api/workouts/inventory").json()}
    b_ids = {i["id"] for i in client_b.get("/api/workouts/inventory").json()}
    assert a_ids == {ia1["id"]}
    assert b_ids == {ib1["id"]}  # B untouched by A's sync


# --- health metrics: same-date upsert must not collide across users ---------

def test_health_metrics_same_date_no_collision(client_a, client_b):
    body_a = {"metrics": [{"date": "2026-07-10", "weight": 70.0}]}
    body_b = {"metrics": [{"date": "2026-07-10", "weight": 80.0}]}
    assert client_a.post("/api/health/metrics", json=body_a).status_code == 200
    assert client_b.post("/api/health/metrics", json=body_b).status_code == 200

    a = client_a.get("/api/health/metrics", params={"start_date": "2026-07-10"}).json()
    b = client_b.get("/api/health/metrics", params={"start_date": "2026-07-10"}).json()
    assert len(a) == 1 and a[0]["weight"] == 70.0
    assert len(b) == 1 and b[0]["weight"] == 80.0


# --- feedback: same workout_id upsert must not collide across users ---------

def test_feedback_same_workout_no_collision(client_a, client_b):
    shared_workout = str(uuid.uuid4())
    assert client_a.post("/api/workouts/feedback", json=feedback_payload(shared_workout, reason="tired")).status_code == 201
    assert client_b.post("/api/workouts/feedback", json=feedback_payload(shared_workout, reason="busy")).status_code == 201

    a = client_a.get("/api/workouts/feedback").json()
    b = client_b.get("/api/workouts/feedback").json()
    assert len(a) == 1 and a[0]["reason"] == "tired"
    assert len(b) == 1 and b[0]["reason"] == "busy"


# --- queue ------------------------------------------------------------------

def test_queue_isolation_and_cross_user_mutation(client_a, client_b):
    created = client_a.post("/api/queue", json={"activityType": "running", "title": "Intervals"})
    assert created.status_code == 201
    item_id = created.json()["id"]

    assert client_b.get("/api/queue").json() == []
    assert client_b.get("/api/queue/pending").json() == []
    # B cannot patch or delete A's queue item
    assert client_b.patch(f"/api/queue/{item_id}", json={"title": "hax"}).status_code == 404
    assert client_b.delete(f"/api/queue/{item_id}").status_code == 404
    # A's item is unchanged
    assert client_a.get("/api/queue").json()[0]["title"] == "Intervals"


# --- plans ------------------------------------------------------------------

def test_plan_isolation(client_a, client_b):
    created = client_a.post("/api/plans", json={"name": "Base", "activityType": "running", "startDate": "2026-07-10"})
    assert created.status_code == 201
    plan_id = created.json()["id"]

    assert client_b.get("/api/plans").json() == []
    assert client_b.get(f"/api/plans/{plan_id}").status_code == 404
    assert client_b.patch(f"/api/plans/{plan_id}", json={"name": "hax"}).status_code == 404
    assert client_b.delete(f"/api/plans/{plan_id}").status_code == 404
    assert client_a.get(f"/api/plans/{plan_id}").json()["name"] == "Base"
