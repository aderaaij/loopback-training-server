"""Acknowledging an applied edit action must fold its composition back
into the queue item.

Bug: the app applies an edit on the watch and then acks it (DELETE
/api/workouts/actions/{id}), which only deleted the action row — the
queue item's workout_data kept the pre-edit structure forever, so
validation, /context, and any future edit read stale compositions while
the watch ran the new one. Delete acks likewise retire the item to
"skipped" (never downgrading "completed") so a workout removed from the
watch stops counting as a scheduled run.
"""

TS = "2026-07-21T06:00:00+00:00"
NEW_TS = "2026-07-22T06:00:00+00:00"

OLD_COMP = {
    "activityType": "running",
    "displayName": "Easy 30 min",
    "location": "outdoor",
    "scheduledDate": TS,
    "blocks": [
        {
            "iterations": 1,
            "steps": [
                {
                    "purpose": "work",
                    "goal": {"type": "time", "value": 1800, "unit": "seconds"},
                    "alert": {"type": "heartRate", "min": 110, "max": 145},
                }
            ],
        }
    ],
}

NEW_COMP = {
    **OLD_COMP,
    "scheduledDate": NEW_TS,
    "blocks": [
        {
            "iterations": 1,
            "steps": [
                {
                    "purpose": "work",
                    "goal": {"type": "time", "value": 1200, "unit": "seconds"},
                    "alert": {"type": "heartRate", "min": 110, "max": 145},
                },
                {
                    "purpose": "work",
                    "goal": {"type": "time", "value": 600, "unit": "seconds"},
                    "alert": {"type": "heartRate", "min": 110, "max": 150},
                },
            ],
        }
    ],
}


def queue_item(client):
    r = client.post(
        "/api/queue",
        json={"activityType": "running", "title": "Easy 30 min", "workoutData": OLD_COMP},
    )
    assert r.status_code == 201
    return r.json()["id"]


def action(client, workout_id, kind="edit", composition=NEW_COMP):
    body = {"workoutId": workout_id, "action": kind}
    if composition is not None:
        body["composition"] = composition
    r = client.post("/api/workouts/actions", json=body)
    assert r.status_code == 201
    return r.json()["id"]


def get_item(client, queue_id):
    return next(i for i in client.get("/api/queue").json() if i["id"] == queue_id)


def test_edit_ack_writes_composition_back(client_a):
    qid = queue_item(client_a)
    aid = action(client_a, qid)
    assert client_a.delete(f"/api/workouts/actions/{aid}").status_code == 200
    item = get_item(client_a, qid)
    assert item["workout_data"] == NEW_COMP
    assert item["scheduled_date"].startswith("2026-07-22")
    # Action is gone.
    assert client_a.get("/api/workouts/actions").json() == []


def test_delete_ack_retires_queue_item(client_a):
    qid = queue_item(client_a)
    aid = action(client_a, qid, kind="delete", composition=None)
    assert client_a.delete(f"/api/workouts/actions/{aid}").status_code == 200
    item = get_item(client_a, qid)
    assert item["status"] == "skipped"
    assert item["workout_data"] == OLD_COMP


def test_delete_ack_never_downgrades_completed(client_a):
    qid = queue_item(client_a)
    aid = action(client_a, qid, kind="delete", composition=None)
    assert client_a.patch(f"/api/queue/{qid}/status", json={"status": "completed"}).status_code == 200
    assert client_a.delete(f"/api/workouts/actions/{aid}").status_code == 200
    assert get_item(client_a, qid)["status"] == "completed"


def test_edit_ack_survives_missing_queue_item(client_a):
    qid = queue_item(client_a)
    aid = action(client_a, qid)
    assert client_a.delete(f"/api/queue/{qid}").status_code == 204
    assert client_a.delete(f"/api/workouts/actions/{aid}").status_code == 200
    assert client_a.get("/api/workouts/actions").json() == []


def test_edit_ack_never_writes_another_users_queue_item(client_a, client_b):
    qid = queue_item(client_b)
    # A's action pointing at B's queue item: acking must not touch B's row.
    aid = action(client_a, qid)
    assert client_a.delete(f"/api/workouts/actions/{aid}").status_code == 200
    assert get_item(client_b, qid)["workout_data"] == OLD_COMP
