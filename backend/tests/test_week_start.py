"""Week-start preference: one per user, followed by the dashboard calendar."""

WEEK_START = "/api/me/week-start"


def test_unset_until_chosen(client_a):
    """NULL until picked; clients read it as Monday, so nothing changes for
    installs that predate the setting."""
    assert client_a.get(WEEK_START).json() == {"weekStart": None, "updatedAt": None}


def test_put_then_get(client_a):
    resp = client_a.put(WEEK_START, json={"weekStart": "sunday"})
    assert resp.status_code == 200
    assert resp.json()["weekStart"] == "sunday"
    assert resp.json()["updatedAt"] is not None
    assert client_a.get(WEEK_START).json()["weekStart"] == "sunday"

    assert client_a.put(WEEK_START, json={"weekStart": "monday"}).json()["weekStart"] == "monday"


def test_resending_the_same_choice_does_not_move_updated_at(client_a):
    first = client_a.put(WEEK_START, json={"weekStart": "sunday"}).json()
    again = client_a.put(WEEK_START, json={"weekStart": "sunday"}).json()
    assert again["updatedAt"] == first["updatedAt"]

    changed = client_a.put(WEEK_START, json={"weekStart": "monday"}).json()
    assert changed["updatedAt"] > first["updatedAt"]


def test_unknown_value_is_rejected(client_a):
    assert client_a.put(WEEK_START, json={"weekStart": "saturday"}).status_code == 422
    assert client_a.put(WEEK_START, json={}).status_code == 422
    assert client_a.get(WEEK_START).json()["weekStart"] is None


def test_a_trailing_slash_still_works(client_a):
    """The SPA catch-all turns a slashed PUT into a 405 that reads like
    "not implemented", so both spellings are registered."""
    assert client_a.put(f"{WEEK_START}/", json={"weekStart": "sunday"}).status_code == 200
    assert client_a.get(f"{WEEK_START}/").json()["weekStart"] == "sunday"


def test_week_start_is_per_user(client_a, client_b):
    client_a.put(WEEK_START, json={"weekStart": "sunday"})
    assert client_b.get(WEEK_START).json()["weekStart"] is None


def test_needs_a_token():
    from fastapi.testclient import TestClient

    from app.main import app

    assert TestClient(app).get(WEEK_START).status_code in (401, 403)
