"""PUT /api/workouts/{id}/plan-link: the athlete counts a recorded workout
for a planned session after the fact, or stops counting it."""

import uuid

SCHEDULED = "2026-07-20T08:00:00+00:00"
STARTED = "2026-07-22T18:00:00+00:00"
ENDED = "2026-07-22T18:45:00+00:00"


def make_plan(client):
    r = client.post("/api/plans", json={"name": "10K Block", "activityType": "running", "startDate": "2026-07-01"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def make_session(client, plan_id=None, title="Intervals 6x800"):
    payload = {
        "activityType": "running",
        "title": title,
        "scheduledDate": SCHEDULED,
        "workoutData": {"displayName": title, "scheduledDate": SCHEDULED},
    }
    if plan_id:
        payload["planId"] = plan_id
    r = client.post("/api/queue", json=payload)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def workout_payload(workout_id=None, activity="running", plan_workout_id=None):
    payload = {
        "id": workout_id or str(uuid.uuid4()),
        "activityType": activity,
        "startDate": STARTED,
        "endDate": ENDED,
        "duration": 2700,
        "totalDistance": 8000,
    }
    if plan_workout_id:
        payload["planWorkoutId"] = plan_workout_id
    return payload


def make_workout(client, **kwargs):
    payload = workout_payload(**kwargs)
    r = client.post("/api/workouts", json=payload)
    assert r.status_code == 201, r.text
    return payload["id"]


def link(client, workout_id, session_id):
    return client.put(f"/api/workouts/{workout_id}/plan-link", json={"planWorkoutId": session_id})


def session(client, session_id):
    return next(i for i in client.get("/api/queue").json() if i["id"] == session_id)


def workout(client, workout_id):
    return client.get(f"/api/workouts/{workout_id}", params={"include_samples": "false"}).json()


def test_linking_completes_the_session_at_the_workouts_end(client_a):
    sid = make_session(client_a)
    wid = make_workout(client_a)

    r = link(client_a, wid, sid)
    assert r.status_code == 200, r.text
    ctx = r.json()
    assert ctx["plan_workout_id"] == sid
    assert ctx["plan_link_manual"] is True
    assert ctx["queue_item"]["status"] == "completed"
    assert ctx["queue_item"]["completed_at"].startswith("2026-07-22T18:45:00")


def test_a_linked_session_counts_towards_the_plan(client_a):
    plan_id = make_plan(client_a)
    sid = make_session(client_a, plan_id=plan_id)
    wid = make_workout(client_a)
    assert client_a.get(f"/api/plans/{plan_id}").json()["progress"]["runs_completed"] == 0

    assert link(client_a, wid, sid).status_code == 200
    assert client_a.get(f"/api/plans/{plan_id}").json()["progress"]["runs_completed"] == 1


def test_any_activity_can_stand_in_for_a_session(client_a):
    sid = make_session(client_a)
    ride = make_workout(client_a, activity="cycling")
    assert link(client_a, ride, sid).status_code == 200
    assert session(client_a, sid)["status"] == "completed"


def test_a_skipped_session_can_be_linked(client_a):
    sid = make_session(client_a)
    assert client_a.patch(f"/api/queue/{sid}/status", json={"status": "skipped"}).status_code == 200
    wid = make_workout(client_a)
    assert link(client_a, wid, sid).status_code == 200
    assert session(client_a, sid)["status"] == "completed"


def test_re_uploading_keeps_a_manual_link(client_a):
    """The app re-sends a workout with its own automatic match, which for a
    workout linked by hand is usually nothing at all."""
    sid = make_session(client_a)
    wid = make_workout(client_a)
    link(client_a, wid, sid)

    r = client_a.post("/api/workouts", json=workout_payload(workout_id=wid))
    assert r.status_code == 201
    assert r.json()["plan_workout_id"] == sid
    assert r.json()["plan_link_manual"] is True


def test_re_uploading_keeps_a_manual_unlink(client_a):
    sid = make_session(client_a)
    wid = make_workout(client_a, plan_workout_id=sid)
    assert link(client_a, wid, None).status_code == 200

    r = client_a.post("/api/workouts", json=workout_payload(workout_id=wid, plan_workout_id=sid))
    assert r.json()["plan_workout_id"] is None


def test_re_uploading_still_updates_an_automatic_match(client_a):
    first, second = make_session(client_a), make_session(client_a)
    wid = make_workout(client_a, plan_workout_id=first)
    r = client_a.post("/api/workouts", json=workout_payload(workout_id=wid, plan_workout_id=second))
    assert r.json()["plan_workout_id"] == second
    assert r.json()["plan_link_manual"] is False


def test_unlinking_reopens_the_session(client_a):
    sid = make_session(client_a)
    wid = make_workout(client_a)
    link(client_a, wid, sid)

    r = link(client_a, wid, None)
    assert r.status_code == 200
    assert r.json()["plan_workout_id"] is None
    assert r.json()["queue_item"] is None
    reopened = session(client_a, sid)
    assert reopened["status"] == "synced"
    assert reopened["completed_at"] is None


def test_unlinking_a_session_the_athlete_skipped_leaves_it_skipped(client_a):
    sid = make_session(client_a)
    r = client_a.post(
        "/api/workouts/feedback",
        json={
            "id": str(uuid.uuid4()),
            "workoutId": sid,
            "workoutName": "Intervals 6x800",
            "scheduledDate": SCHEDULED,
            "detectedAt": SCHEDULED,
            "reason": "tired",
            "action": "skip",
            "dismissed": False,
        },
    )
    assert r.status_code == 201
    wid = make_workout(client_a)
    link(client_a, wid, sid)
    link(client_a, wid, None)
    assert session(client_a, sid)["status"] == "skipped"


def test_moving_a_link_reopens_the_session_left_behind(client_a):
    first, second = make_session(client_a, title="Easy 5K"), make_session(client_a, title="Tempo 8K")
    wid = make_workout(client_a)
    link(client_a, wid, first)
    link(client_a, wid, second)

    assert session(client_a, first)["status"] == "synced"
    assert session(client_a, second)["status"] == "completed"
    assert workout(client_a, wid)["plan_workout_id"] == second


def test_a_session_counts_one_workout(client_a):
    """Linking a second workout takes the first one off, and marks that as
    the athlete's doing so a re-upload does not put it back."""
    sid = make_session(client_a)
    auto = make_workout(client_a, plan_workout_id=sid)
    chosen = make_workout(client_a)

    assert link(client_a, chosen, sid).status_code == 200
    assert workout(client_a, auto)["plan_workout_id"] is None
    assert workout(client_a, chosen)["plan_workout_id"] == sid
    assert session(client_a, sid)["status"] == "completed"

    r = client_a.post("/api/workouts", json=workout_payload(workout_id=auto, plan_workout_id=sid))
    assert r.json()["plan_workout_id"] is None


def test_the_inventory_reports_a_linked_session_as_complete(client_a):
    """The device never saw the run start from its schedule, so its own
    snapshot says incomplete. The coach reads this list to find missed runs."""
    sid = make_session(client_a)
    item = {
        "id": sid,
        "displayName": "Intervals 6x800",
        "date": {"year": 2026, "month": 7, "day": 20, "hour": 8, "minute": 0},
        "complete": False,
    }
    assert client_a.put("/api/workouts/inventory", json=[item]).status_code == 200
    assert client_a.get("/api/workouts/inventory").json()[0]["complete"] is False

    link(client_a, make_workout(client_a), sid)
    assert client_a.get("/api/workouts/inventory").json()[0]["complete"] is True


def test_someone_elses_session_or_workout_is_not_found(client_a, client_b):
    theirs = make_session(client_b)
    mine = make_workout(client_a)
    assert link(client_a, mine, theirs).status_code == 404
    assert link(client_b, mine, theirs).status_code == 404
    assert session(client_b, theirs)["status"] == "pending"
