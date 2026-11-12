"""Display-units preference: one per user, shared by dashboard, app and coach."""

UNITS = "/api/me/units"


def test_unset_until_chosen(client_a):
    """NULL, not metric: the phone needs to tell "never picked" from "picked
    metric" to fall back to the device's region."""
    assert client_a.get(UNITS).json() == {"units": None, "updatedAt": None}


def test_put_then_get(client_a):
    resp = client_a.put(UNITS, json={"units": "imperial"})
    assert resp.status_code == 200
    assert resp.json()["units"] == "imperial"
    assert resp.json()["updatedAt"] is not None
    assert client_a.get(UNITS).json()["units"] == "imperial"

    assert client_a.put(UNITS, json={"units": "metric"}).json()["units"] == "metric"


def test_resending_the_same_choice_does_not_move_updated_at(client_a):
    first = client_a.put(UNITS, json={"units": "imperial"}).json()
    again = client_a.put(UNITS, json={"units": "imperial"}).json()
    assert again["updatedAt"] == first["updatedAt"]

    changed = client_a.put(UNITS, json={"units": "metric"}).json()
    assert changed["updatedAt"] > first["updatedAt"]


def test_unknown_value_is_rejected(client_a):
    assert client_a.put(UNITS, json={"units": "nautical"}).status_code == 422
    assert client_a.put(UNITS, json={}).status_code == 422
    assert client_a.get(UNITS).json()["units"] is None


def test_a_trailing_slash_still_works(client_a):
    """Same reason as data consent: the SPA catch-all turns a slashed PUT
    into a 405 that reads like "not implemented"."""
    assert client_a.put(f"{UNITS}/", json={"units": "imperial"}).status_code == 200
    assert client_a.get(f"{UNITS}/").json()["units"] == "imperial"


def test_units_are_per_user(client_a, client_b):
    client_a.put(UNITS, json={"units": "imperial"})
    assert client_b.get(UNITS).json()["units"] is None


def test_needs_a_token():
    from fastapi.testclient import TestClient

    from app.main import app

    assert TestClient(app).get(UNITS).status_code in (401, 403)


def test_plan_context_tells_the_coach(client_a):
    """The coach reads units from the call it makes first in every conversation."""
    ctx = client_a.get("/api/plan-notes/context").json()
    assert ctx["units"] is None
    assert "not chosen" in ctx["units_hint"]

    client_a.put(UNITS, json={"units": "imperial"})
    ctx = client_a.get("/api/plan-notes/context").json()
    assert ctx["units"] == "imperial"
    assert "miles" in ctx["units_hint"]
