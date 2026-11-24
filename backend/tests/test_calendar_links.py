"""Calendar entries carry the ids the dashboard links to.

Runs carry the queue item (`queueId`) and, once one was recorded for it, the
workout (`workoutId`, the one whose plan_workout_id is that item). Strength
sessions have no queue item; their `workoutId` is the strength workout on the
same day, the earliest if there are several.
"""

import uuid

DAY = "2026-07-20"  # a Monday
SCHEDULED = f"{DAY}T08:00:00+00:00"


def queue_run(client, sched=SCHEDULED):
    r = client.post("/api/queue", json={"activityType": "running", "title": "Easy 5K", "scheduledDate": sched})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def post_workout(client, start, activity="running", plan_workout_id=None, workout_id=None):
    payload = {
        "id": workout_id or str(uuid.uuid4()),
        "activityType": activity,
        "startDate": start,
        "endDate": start.replace("T08", "T09"),
        "duration": 3600,
    }
    if plan_workout_id:
        payload["planWorkoutId"] = plan_workout_id
    r = client.post("/api/workouts", json=payload)
    assert r.status_code == 201, r.text
    return payload["id"]


def schedule_strength(client):
    plan = client.post("/api/plans", json={"name": "Lifting", "activityType": "strength", "startDate": DAY})
    assert plan.status_code == 201, plan.text
    r = client.put(
        f"/api/plans/{plan.json()['id']}/schedule",
        json={"startDate": DAY, "weeks": 1, "days": {"mon": {"title": "Upper A"}}},
    )
    assert r.status_code == 200, r.text


def entries(client):
    r = client.get("/api/schedule/calendar", params={"from": DAY, "to": DAY})
    assert r.status_code == 200, r.text
    return {e["kind"]: e for e in r.json()["entries"]}


def test_pending_run_has_queue_id_and_no_workout(client_a):
    item = queue_run(client_a)

    run = entries(client_a)["run"]
    assert run["queueId"] == item
    assert run["workoutId"] is None


def test_completed_run_links_to_its_workout(client_a):
    item = queue_run(client_a)
    workout = post_workout(client_a, SCHEDULED, plan_workout_id=item)

    run = entries(client_a)["run"]
    assert run["queueId"] == item
    assert run["workoutId"] == workout


def test_run_links_to_workout_recorded_on_another_day(client_a):
    item = queue_run(client_a)
    workout = post_workout(client_a, "2026-07-22T08:00:00+00:00", plan_workout_id=item)

    assert entries(client_a)["run"]["workoutId"] == workout


def test_run_with_several_linked_workouts_shows_the_newest(client_a):
    item = queue_run(client_a)
    post_workout(client_a, "2026-07-20T06:00:00+00:00", plan_workout_id=item)
    newest = post_workout(client_a, "2026-07-20T18:00:00+00:00", plan_workout_id=item)

    assert entries(client_a)["run"]["workoutId"] == newest


def test_strength_entry_without_workout(client_a):
    schedule_strength(client_a)

    strength = entries(client_a)["strength"]
    assert strength["queueId"] is None
    assert strength["workoutId"] is None


def test_strength_entry_links_to_that_days_workout(client_a):
    schedule_strength(client_a)
    workout = post_workout(client_a, SCHEDULED, activity="traditionalStrength")

    strength = entries(client_a)["strength"]
    assert strength["workoutId"] == workout
    assert strength["completed"] is True


def test_strength_entry_with_several_workouts_shows_the_earliest(client_a):
    schedule_strength(client_a)
    ids = [
        post_workout(client_a, f"{DAY}T{hour}:00:00+00:00", activity="traditionalStrength")
        for hour in ("17", "07")
    ]

    assert entries(client_a)["strength"]["workoutId"] == ids[1]


def test_workout_ids_are_not_shared_between_users(client_a, client_b):
    item = queue_run(client_a)
    post_workout(client_a, SCHEDULED, plan_workout_id=item)

    r = client_b.get("/api/schedule/calendar", params={"from": DAY, "to": DAY})
    assert r.json()["entries"] == []
