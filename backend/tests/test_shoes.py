"""Shoe tracking: pairs, their mileage, and which pair a workout was run in."""

import uuid
from datetime import datetime, timedelta, timezone

SHOES = "/api/shoes"


def make_shoe(client, name="Pegasus 41", **extra):
    r = client.post(SHOES, json={"name": name, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def make_workout(client, activity="running", distance=10_000.0, start=None, workout_id=None):
    start = start or datetime.now(timezone.utc) + timedelta(minutes=1)
    payload = {
        "id": workout_id or str(uuid.uuid4()),
        "activityType": activity,
        "startDate": start.isoformat(),
        "endDate": (start + timedelta(minutes=50)).isoformat(),
        "duration": 3000,
        "totalDistance": distance,
    }
    r = client.post("/api/workouts", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def shoe(client, shoe_id):
    return next(s for s in client.get(SHOES).json() if s["id"] == shoe_id)


def test_a_new_pair_starts_at_its_starting_mileage(client_a):
    created = make_shoe(client_a, startDistance=250_000, targetDistance=800_000)
    assert created["distance"] == 250_000
    assert created["workoutCount"] == 0
    assert created["lastUsedAt"] is None
    assert created["isDefault"] is False
    assert created["retiredAt"] is None


def test_new_runs_go_on_the_default_pair(client_a):
    pair = make_shoe(client_a, startDistance=100_000, isDefault=True)
    run = make_workout(client_a, distance=12_400)
    assert run["shoe_id"] == pair["id"]

    listed = shoe(client_a, pair["id"])
    assert listed["distance"] == 112_400
    assert listed["workoutCount"] == 1
    assert listed["lastUsedAt"] is not None


def test_only_runs_get_the_default_pair(client_a):
    make_shoe(client_a, isDefault=True)
    assert make_workout(client_a, activity="walking")["shoe_id"] is None
    assert make_workout(client_a, activity="cycling")["shoe_id"] is None


def test_no_default_means_no_pair(client_a):
    make_shoe(client_a)
    assert make_workout(client_a)["shoe_id"] is None


def test_runs_from_before_the_pair_existed_are_not_assigned(client_a):
    """Their distance is what the starting mileage stands for. A reinstall
    re-uploading a year of runs must not pile them onto today's default."""
    pair = make_shoe(client_a, startDistance=300_000, isDefault=True)
    old = make_workout(client_a, start=datetime.now(timezone.utc) - timedelta(days=30))
    assert old["shoe_id"] is None
    assert shoe(client_a, pair["id"])["distance"] == 300_000


def test_re_uploading_a_workout_keeps_the_athletes_choice(client_a):
    default = make_shoe(client_a, "Daily", isDefault=True)
    race = make_shoe(client_a, "Race")
    run = make_workout(client_a)
    assert run["shoe_id"] == default["id"]

    r = client_a.put(f"/api/workouts/{run['id']}/shoe", json={"shoeId": race["id"]})
    assert r.status_code == 200
    assert r.json()["shoe_id"] == race["id"]
    assert make_workout(client_a, workout_id=run["id"])["shoe_id"] == race["id"]

    # Taken off altogether: a re-upload must not put the default back.
    assert client_a.put(f"/api/workouts/{run['id']}/shoe", json={"shoeId": None}).json()["shoe_id"] is None
    assert make_workout(client_a, workout_id=run["id"])["shoe_id"] is None
    assert client_a.get(f"/api/workouts/{run['id']}").json()["shoe_id"] is None


def test_any_workout_can_be_given_a_pair_by_hand(client_a):
    pair = make_shoe(client_a)
    walk = make_workout(client_a, activity="walking", distance=4_000)
    assert client_a.put(f"/api/workouts/{walk['id']}/shoe", json={"shoeId": pair["id"]}).status_code == 200
    assert shoe(client_a, pair["id"])["distance"] == 4_000


def test_one_default_at_a_time(client_a):
    first = make_shoe(client_a, "First", isDefault=True)
    second = make_shoe(client_a, "Second", isDefault=True)
    assert shoe(client_a, first["id"])["isDefault"] is False
    assert shoe(client_a, second["id"])["isDefault"] is True

    assert client_a.patch(f"{SHOES}/{first['id']}", json={"isDefault": True}).json()["isDefault"] is True
    assert shoe(client_a, second["id"])["isDefault"] is False


def test_retiring_the_default_stops_new_runs_landing_on_it(client_a):
    pair = make_shoe(client_a, isDefault=True)
    retired = client_a.patch(f"{SHOES}/{pair['id']}", json={"retired": True}).json()
    assert retired["retiredAt"] is not None
    assert retired["isDefault"] is False
    assert make_workout(client_a)["shoe_id"] is None

    assert client_a.patch(f"{SHOES}/{pair['id']}", json={"isDefault": True}).status_code == 422

    back = client_a.patch(f"{SHOES}/{pair['id']}", json={"retired": False, "isDefault": True}).json()
    assert back["retiredAt"] is None
    assert back["isDefault"] is True


def test_patch_changes_only_what_is_sent(client_a):
    pair = make_shoe(client_a, "Old name", startDistance=50_000, targetDistance=800_000)
    renamed = client_a.patch(f"{SHOES}/{pair['id']}", json={"name": "  New name "}).json()
    assert renamed["name"] == "New name"
    assert renamed["startDistance"] == 50_000
    assert renamed["targetDistance"] == 800_000

    no_target = client_a.patch(f"{SHOES}/{pair['id']}", json={"targetDistance": None}).json()
    assert no_target["targetDistance"] is None
    assert no_target["name"] == "New name"


def test_in_use_pairs_list_before_retired_ones(client_a):
    old = make_shoe(client_a, "Old")
    new = make_shoe(client_a, "New")
    client_a.patch(f"{SHOES}/{new['id']}", json={"retired": True})
    assert [s["id"] for s in client_a.get(SHOES).json()] == [old["id"], new["id"]]


def test_deleting_a_pair_keeps_its_workouts(client_a):
    pair = make_shoe(client_a, isDefault=True)
    run = make_workout(client_a)
    assert client_a.delete(f"{SHOES}/{pair['id']}").status_code == 204
    assert client_a.get(SHOES).json() == []
    assert client_a.get(f"/api/workouts/{run['id']}").json()["shoe_id"] is None


def test_bad_input_is_rejected(client_a):
    assert client_a.post(SHOES, json={"name": "   "}).status_code == 422
    assert client_a.post(SHOES, json={"name": "x", "startDistance": -1}).status_code == 422
    assert client_a.post(SHOES, json={"name": "x", "targetDistance": 0}).status_code == 422
    assert client_a.post(SHOES, json={}).status_code == 422


def test_pairs_are_per_user(client_a, client_b):
    pair = make_shoe(client_a, isDefault=True)
    assert client_b.get(SHOES).json() == []
    assert client_b.patch(f"{SHOES}/{pair['id']}", json={"name": "Mine now"}).status_code == 404
    assert client_b.delete(f"{SHOES}/{pair['id']}").status_code == 404

    # B's runs don't land on A's default, and B can't borrow A's pair.
    run_b = make_workout(client_b)
    assert run_b["shoe_id"] is None
    assert client_b.put(f"/api/workouts/{run_b['id']}/shoe", json={"shoeId": pair["id"]}).status_code == 404

    run_a = make_workout(client_a)
    assert client_b.put(f"/api/workouts/{run_a['id']}/shoe", json={"shoeId": None}).status_code == 404


def test_needs_a_token():
    from fastapi.testclient import TestClient

    from app.main import app

    assert TestClient(app).get(SHOES).status_code in (401, 403)
