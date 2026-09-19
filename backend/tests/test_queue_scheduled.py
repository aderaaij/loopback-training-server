"""A fresh install must be able to restore the watch schedule.

Bug: `synced` is per account, not per device. Once the old phone confirmed a
plan's runs, a reinstall or a new phone got an empty pending queue, so its
watch, calendar and "Upcoming" list stayed empty while the plan still showed
every run. GET /api/workouts/queue/scheduled lists the delivered runs that are
still due, so the app can re-schedule whatever its watch is missing.
"""

import uuid

TODAY = "2026-09-19T00:00:00Z"


def queue_item(client, title="Easy 5K", sched="2026-09-20T07:00:00Z"):
    r = client.post(
        "/api/queue",
        json={
            "activityType": "running",
            "title": title,
            "workoutData": {"displayName": title, "scheduledDate": sched},
        },
    )
    assert r.status_code == 201
    return r.json()["id"]


def synced_item(client, **kw):
    qid = queue_item(client, **kw)
    assert client.patch(f"/api/workouts/queue/{qid}").status_code == 204
    return qid


def scheduled(client, since=TODAY):
    r = client.get("/api/workouts/queue/scheduled", params={"from": since})
    assert r.status_code == 200
    return r.json()


def test_lists_delivered_items_still_due_in_date_order(client_a):
    later = synced_item(client_a, title="Long run", sched="2026-09-27T08:00:00Z")
    sooner = synced_item(client_a, title="Intervals", sched="2026-09-21T07:00:00Z")
    fetched = queue_item(client_a, title="Tempo", sched="2026-09-23T07:00:00Z")
    assert client_a.patch(f"/api/queue/{fetched}/status", json={"status": "fetched"}).status_code == 200

    items = scheduled(client_a)
    assert [i["id"] for i in items] == [sooner, fetched, later]
    # Same shape as the pending endpoint: the composition with the queue id injected.
    assert items[0] == {"id": sooner, "displayName": "Intervals", "scheduledDate": "2026-09-21T07:00:00Z"}


def test_today_counts_but_earlier_days_do_not(client_a):
    this_morning = synced_item(client_a, sched="2026-09-19T06:00:00Z")
    yesterday = synced_item(client_a, sched="2026-09-18T07:00:00Z")
    ids = [i["id"] for i in scheduled(client_a)]
    assert this_morning in ids
    assert yesterday not in ids


def test_excludes_pending_completed_and_skipped(client_a):
    pending = queue_item(client_a)  # still offered by the pending endpoint instead
    completed = synced_item(client_a)
    skipped = synced_item(client_a)
    client_a.patch(f"/api/queue/{completed}/status", json={"status": "completed"})
    client_a.patch(f"/api/queue/{skipped}/status", json={"status": "skipped"})
    ids = [i["id"] for i in scheduled(client_a)]
    assert pending not in ids and completed not in ids and skipped not in ids


def test_acked_coach_delete_is_not_restored(client_a):
    qid = synced_item(client_a)
    action = client_a.post("/api/workouts/actions", json={"workoutId": qid, "action": "delete"}).json()
    assert client_a.delete(f"/api/workouts/actions/{action['id']}").status_code == 200
    assert all(i["id"] != qid for i in scheduled(client_a))


def test_is_owner_scoped(client_a, client_b):
    qid = synced_item(client_a)
    assert all(i["id"] != qid for i in scheduled(client_b))


def test_from_is_required(client_a):
    assert client_a.get("/api/workouts/queue/scheduled").status_code == 422


# --- Moving a missed run re-dates the queue item ------------------------------


def move_payload(queue_id, new_date, **over):
    p = {
        "id": str(uuid.uuid4()),
        "workoutId": str(queue_id),
        "workoutName": "Easy 5K",
        "scheduledDate": "2026-09-17T07:00:00Z",
        "detectedAt": "2026-09-18T07:00:00Z",
        "acknowledgedAt": "2026-09-18T07:00:00Z",
        "reason": "busy",
        "action": "move",
        "newDate": new_date,
        "dismissed": False,
    }
    p.update(over)
    return p


def test_move_feedback_re_dates_the_item_so_a_restore_uses_the_new_day(client_a):
    qid = synced_item(client_a, sched="2026-09-17T07:00:00Z")  # missed, before today
    assert all(i["id"] != qid for i in scheduled(client_a))

    r = client_a.post("/api/workouts/feedback", json=move_payload(qid, "2026-09-22T06:30:00.250+01:00"))
    assert r.status_code == 201

    [item] = [i for i in scheduled(client_a) if i["id"] == qid]
    # Normalised to whole-second UTC: the app's ISO 8601 decoder rejects fractions.
    assert item["scheduledDate"] == "2026-09-22T05:30:00Z"
    row = next(r for r in client_a.get("/api/queue").json() if r["id"] == qid)
    assert row["scheduled_date"].startswith("2026-09-22T05:30:00")
    assert row["status"] == "synced"


def test_dismissed_move_leaves_the_date_alone(client_a):
    qid = synced_item(client_a, sched="2026-09-17T07:00:00Z")
    client_a.post("/api/workouts/feedback", json=move_payload(qid, "2026-09-22T07:00:00Z", dismissed=True))
    assert all(i["id"] != qid for i in scheduled(client_a))


def test_move_never_re_dates_a_completed_item(client_a):
    qid = synced_item(client_a, sched="2026-09-17T07:00:00Z")
    client_a.patch(f"/api/queue/{qid}/status", json={"status": "completed"})
    client_a.post("/api/workouts/feedback", json=move_payload(qid, "2026-09-22T07:00:00Z"))
    row = next(r for r in client_a.get("/api/queue").json() if r["id"] == qid)
    assert row["scheduled_date"].startswith("2026-09-17")


def test_move_ignores_another_users_item(client_a, client_b):
    qid = synced_item(client_a, sched="2026-09-17T07:00:00Z")
    client_b.post("/api/workouts/feedback", json=move_payload(qid, "2026-09-22T07:00:00Z"))
    row = next(r for r in client_a.get("/api/queue").json() if r["id"] == qid)
    assert row["scheduled_date"].startswith("2026-09-17")
