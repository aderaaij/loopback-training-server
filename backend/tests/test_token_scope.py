"""Coach tokens: good for what the coach's tools call, refused everywhere else.

The properties that matter here:
  - the list of what a coach token may call is exactly what the coach's own
    client calls, read from that client's source, so the two cannot drift;
  - everything else that takes a token refuses a coach token, checked by
    walking every route the app has rather than a few picked by hand, so a
    route added later is covered without anyone thinking of it;
  - what the athlete shares holds for a coach token without the header that
    a full token needs to be scoped;
  - a full token is untouched by all of this.
"""

import re
import uuid
from pathlib import Path

import pytest
import training_mcp.services.api_client as installed_client
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.routing import Match

import app.auth as auth_module
from app.main import app
from app.token_scope import COACH_ROUTES

REFUSAL = "This token is for the coach only"


def _bearer(token: str) -> TestClient:
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {token}"
    return c


def _mint(client, name="Coach · Claude Code", **body) -> dict:
    r = client.post("/api/auth/tokens", json={"name": name, **body})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture()
def coach_a(client_a) -> TestClient:
    """A coach token of alice's."""
    return _bearer(_mint(client_a, scope="coach")["token"])


# ── the list against the coach's client ──

# A call as the client writes them: the method and the path as literals, the
# path being the whole argument. One whose path goes on after its closing
# quote (`"/api/x" + suffix`) does not match, and is then caught by the count
# in the first test below instead of being read as the shorter path.
_REQUEST = re.compile(r'self\._request\(\s*"([A-Z]+)",\s*f?"(/api/[^"?]*)"\s*[,)]')
_DELETE = re.compile(r'self\._delete\(\s*f?"(/api/[^"?]*)"\s*[,)]')

# The coach's client as it is in this checkout (`mcp/` sits next to `backend/`,
# and at /mcp next to /app in the image). The backend's environment holds a
# built copy of that package, which on a developer's machine can be an older
# one than the source being tested; it is only the fallback.
_IN_CHECKOUT = Path(__file__).resolve().parents[2] / "mcp" / "training_mcp" / "services" / "api_client.py"
CLIENT = _IN_CHECKOUT if _IN_CHECKOUT.exists() else Path(installed_client.__file__)


def _route_for(method: str, path: str) -> str | None:
    """The path of the route that would answer this request, as registered."""
    scope = {"type": "http", "method": method, "path": path}
    for route in app.router.routes:
        if route.matches(scope)[0] == Match.FULL:
            return route.path
    return None


def _calls_in_the_client() -> set[tuple[str, str]]:
    source = CLIENT.read_text()
    calls = {(method, path) for method, path in _REQUEST.findall(source)}
    calls |= {("DELETE", path) for path in _DELETE.findall(source)}
    # A path's own values do not matter to which route answers it.
    return {(method, re.sub(r"\{[^}]+\}", "0", path)) for method, path in calls}


def test_every_request_the_client_makes_can_be_read_from_its_source():
    """The comparison below is only as good as this reading of the file.

    A call written some other way (the method in a variable, the path built
    beforehand) would not be seen, and its route would be missing from the
    list with no test saying so. Then this fails instead.
    """
    source = CLIENT.read_text()
    assert len(_REQUEST.findall(source)) == source.count("self._request(")
    assert len(_DELETE.findall(source)) == source.count("self._delete(")
    # Those two helpers are the only places a request leaves the client. A
    # third one that sends its own would be a call nothing here reads.
    assert source.count("httpx.AsyncClient(") == 2
    # And nothing else in the package talks to the API, on its own or by
    # reaching into the client's helpers from another file.
    package = CLIENT.parents[1]
    assert package.name == "training_mcp"
    others = [p for p in package.rglob("*.py") if p != CLIENT]
    assert len(others) > 10
    for needle in ("httpx", "._request(", "._delete("):
        assert [p.name for p in others if needle in p.read_text()] == [], needle


def test_the_list_is_exactly_what_the_coach_calls():
    called = {(method, _route_for(method, path)) for method, path in _calls_in_the_client()}
    # A tool calling something unlisted works with a full token and answers
    # 403 for every assistant that signed in.
    assert called - COACH_ROUTES == set(), "add these to COACH_ROUTES in app/token_scope.py"
    # An entry no tool uses is access for no reason.
    assert COACH_ROUTES - called == set(), "nothing in the coach's client calls these any more"


# ── what a coach token is refused ──


# Everything the app answers without a token. The walk below sorts every
# route into "asks for a token" or this list, so a new route that is neither
# (one that checks a token some way of its own, which is the one kind the
# refusal in get_current_user would not cover) fails the test by name.
PUBLIC = {
    ("GET", "/api/health"),
    ("POST", "/api/auth/login"),
    ("GET", "/api/auth/setup"),
    ("POST", "/api/auth/setup"),
    ("GET", "/.well-known/oauth-protected-resource"),
    ("GET", "/.well-known/oauth-protected-resource/mcp"),
    ("GET", "/.well-known/oauth-authorization-server"),
    ("GET", "/oauth/authorize"),
    ("POST", "/oauth/authorize"),
    ("POST", "/oauth/token"),
    # The dashboard's own files.
    ("GET", "/"),
    ("GET", "/{full_path:path}"),
}
# FastAPI's own pages, which are plain Starlette routes.
DOCS = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


def _routes_taking_a_token() -> list[tuple[str, str]]:
    """Every method and path in the app that asks for a bearer token.

    Found by asking without one: the refusal for a missing token is FastAPI's
    own, the same for every such route. (/oauth/token answers 401 as well,
    for a client it does not know, which has nothing to do with tokens.)
    """
    anon = TestClient(app)
    found, public = [], set()
    for route in app.router.routes:
        if not isinstance(route, APIRoute):
            assert route.path in DOCS, f"a route of another kind: {route.path}"
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            if ":path" in route.path:
                public.add((method, route.path))
                continue
            r = anon.request(method, re.sub(r"\{[^}]+\}", str(uuid.uuid4()), route.path))
            if r.status_code in (401, 403) and r.json() == {"detail": "Not authenticated"}:
                found.append((method, route.path))
            else:
                public.add((method, route.path))
    assert public == PUBLIC
    return found


def test_everything_else_refuses_a_coach_token(coach_a):
    routes = _routes_taking_a_token()
    # The walk found the API, not a handful of routes.
    assert len(routes) > 100
    assert COACH_ROUTES <= set(routes)

    let_through = []
    for method, template in routes:
        if (method, template) in COACH_ROUTES:
            continue
        r = coach_a.request(method, re.sub(r"\{[^}]+\}", str(uuid.uuid4()), template))
        if r.status_code != 403 or REFUSAL not in r.json().get("detail", ""):
            let_through.append((method, template, r.status_code))
    assert let_through == []


@pytest.mark.parametrize(
    "method, path",
    [
        # More tokens, or fewer: a token made here would outlive this one.
        ("POST", "/api/auth/tokens"),
        ("GET", "/api/auth/me"),
        ("DELETE", f"/api/auth/tokens/{uuid.uuid4()}"),
        ("POST", "/api/auth/password"),
        # What the coach is allowed to see.
        ("PUT", "/api/me/data-consent"),
        # Letting another assistant in.
        ("POST", f"/api/oauth/requests/{uuid.uuid4()}/approve"),
        # Data only the phone sends.
        ("POST", "/api/workouts"),
        ("POST", "/api/health/metrics"),
        ("POST", "/api/nutrition"),
        ("GET", "/api/admin/users"),
    ],
)
def test_what_a_coach_token_is_kept_from(coach_a, method, path):
    r = coach_a.request(method, path, json={"name": "another", "domains": ["training", "body"]})
    assert r.status_code == 403
    assert REFUSAL in r.json()["detail"]


def test_a_coach_token_cannot_make_itself_a_full_one(coach_a, client_a):
    assert coach_a.post("/api/auth/tokens", json={"name": "sibling"}).status_code == 403
    assert [t["name"] for t in client_a.get("/api/auth/me").json()["tokens"]] == ["test-device", "Coach · Claude Code"]


def test_a_coach_token_does_the_coachs_work(coach_a):
    assert coach_a.get("/api/workouts").status_code == 200
    assert coach_a.get("/api/plans").status_code == 200
    assert coach_a.get("/api/me/data-consent").status_code == 200
    note = coach_a.post("/api/plan-notes", json={"summary": "Easy week after the cold", "kind": "decision"})
    assert note.status_code in (200, 201), note.text


def test_a_refusal_is_a_403_and_the_token_stays_good(coach_a):
    """A 401 would tell an assistant to sign in again, for a token that works."""
    assert coach_a.get("/api/auth/me").status_code == 403
    assert coach_a.get("/api/workouts").status_code == 200


def test_the_coach_endpoint_takes_a_coach_token(client_a):
    assert auth_module.token_is_live(_mint(client_a, scope="coach")["token"]) is True


# ── what the athlete shares ──

METRICS = "/api/health/metrics"
DAY = "2026-07-20"


@pytest.fixture()
def metrics_day(client_a):
    client_a.post(METRICS, json={"metrics": [{"date": DAY, "sleep_duration": 7.5, "weight": 74.2, "steps": 9000}]})
    return DAY


def test_what_the_athlete_shares_holds_without_the_header(client_a, coach_a, metrics_day):
    client_a.put("/api/me/data-consent", json={"domains": ["activity"]})

    row = coach_a.get(METRICS, params={"start_date": metrics_day}).json()[0]
    assert row["steps"] == 9000
    assert "weight" not in row and "sleep_duration" not in row

    # The same request with the athlete's own token is the dashboard asking.
    assert client_a.get(METRICS, params={"start_date": metrics_day}).json()[0]["weight"] == 74.2


def test_a_table_the_athlete_does_not_share_is_refused_as_not_shared(client_a, coach_a, metrics_day):
    client_a.put("/api/me/data-consent", json={"domains": []})
    r = coach_a.get(METRICS, params={"start_date": metrics_day})
    assert r.status_code == 403
    assert "not share" in r.json()["detail"]


# ── making and listing them ──


def test_a_token_is_full_unless_asked_otherwise(client_a):
    made = _mint(client_a, name="My script")
    assert _bearer(made["token"]).get("/api/auth/me").status_code == 200

    kinds = {t["name"]: t["scope"] for t in client_a.get("/api/auth/me").json()["tokens"]}
    assert kinds == {"test-device": "full", "My script": "full"}


def test_the_token_list_says_which_kind(client_a, client_admin, user_a):
    _mint(client_a, scope="coach")
    kinds = {t["name"]: t["scope"] for t in client_a.get("/api/auth/me").json()["tokens"]}
    assert kinds == {"test-device": "full", "Coach · Claude Code": "coach"}

    for_admin = client_admin.get(f"/api/admin/users/{user_a[0]}/tokens").json()
    assert {t["name"]: t["scope"] for t in for_admin} == kinds


def test_an_unknown_kind_is_not_a_token(client_a):
    r = client_a.post("/api/auth/tokens", json={"name": "x", "scope": "admin"})
    assert r.status_code == 422


def test_a_login_makes_a_full_token(session_factory, user_a):
    r = TestClient(app).post("/api/auth/login", json={"username": "alice", "password": "pw"})
    assert _bearer(r.json()["token"]).get("/api/auth/me").status_code == 200


def test_the_command_line_makes_either_kind(session_factory, user_a, monkeypatch, capsys):
    import argparse

    import app.cli as cli

    monkeypatch.setattr(cli, "SessionLocal", session_factory)
    made = {}
    for coach in (True, False):
        cli.cmd_create_token(argparse.Namespace(username="alice", name="agent", coach=coach))
        made[coach] = re.search(r"tapi_\S+", capsys.readouterr().out).group(0)

    assert _bearer(made[True]).get("/api/auth/me").status_code == 403
    assert _bearer(made[True]).get("/api/workouts").status_code == 200
    assert _bearer(made[False]).get("/api/auth/me").status_code == 200


# ── the audit trail ──


def _events(client_admin, event: str) -> list[dict]:
    return [e for e in client_admin.get("/api/admin/events").json() if e["event"] == event]


def test_a_refusal_is_recorded_once(coach_a, client_admin):
    for _ in range(3):
        assert coach_a.get("/api/auth/me").status_code == 403
    assert coach_a.post("/api/auth/tokens", json={"name": "x"}).status_code == 403

    [event] = _events(client_admin, "token_rejected")
    assert event["username"] == "alice"
    assert event["detail"] == {
        "reason": "scope", "name": "Coach · Claude Code", "method": "GET", "path": "/api/auth/me",
    }


def test_making_a_coach_token_is_recorded_as_one(client_a, client_admin):
    _mint(client_a, scope="coach")
    _mint(client_a, name="My script")
    details = [e["detail"] for e in _events(client_admin, "token_created")]
    assert {"name": "Coach · Claude Code", "scope": "coach"} in details
    assert {"name": "My script"} in details
