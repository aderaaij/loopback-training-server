"""The coach MCP is served from the API's own port at /mcp.

These cover the wiring only — that a client reaches a live MCP at the bare
path and that the door asks for credentials. Tool behaviour is covered by the
MCP's own suite (mcp/tests), which runs against FastMCP's in-memory transport.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, update

import app.main as main_module
from app.main import app
from app.models.api_token import ApiToken
from app.models.user import User

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "pytest", "version": "0"},
    },
}
ACCEPT = {"Accept": "application/json, text/event-stream"}
CHALLENGE = 'Bearer resource_metadata="http://testserver/.well-known/oauth-protected-resource/mcp"'


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", **ACCEPT}


@pytest.fixture(scope="module")
def live():
    """A client inside the app's lifespan — the MCP session manager only runs
    there, and can only be started once per process, hence module scope."""
    mp = pytest.MonkeyPatch()

    async def no_backups():
        return None

    # The lifespan also starts the backup scheduler; keep pg_dump out of tests.
    mp.setattr(main_module, "run_scheduler", no_backups)
    with TestClient(app) as c:
        yield c
    mp.undo()


# The bare path is the one every MCP client POSTs to. Without the dispatch it
# falls through to the GET-only SPA catch-all and answers 405.
@pytest.mark.parametrize("path", ["/mcp", "/mcp/"])
def test_initialize_reaches_the_mcp(live, user_a, path):
    r = live.post(path, json=INITIALIZE, headers=headers(user_a[1]))
    assert r.status_code == 200, r.text
    assert "training-mcp" in r.text
    assert r.headers.get("mcp-session-id")


# The challenge is where an assistant that signs in through OAuth learns
# where to start (app/oauth.py).
@pytest.mark.parametrize("auth", [None, "Basic abc", "Bearer"])
def test_no_bearer_token_is_401(live, auth):
    sent = dict(ACCEPT)
    if auth:
        sent["Authorization"] = auth
    r = live.post("/mcp", json=INITIALIZE, headers=sent)
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == CHALLENGE
    assert "Create token" in r.json()["detail"]


# A token that will not work must not get a session: the 401 is how a client
# that signed in learns it has to do so again.
def test_a_made_up_token_is_401(live):
    r = live.post("/mcp", json=INITIALIZE, headers=headers("tapi_anything"))
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == CHALLENGE + ', error="invalid_token"'
    assert "not valid" in r.json()["detail"]
    assert "mcp-session-id" not in r.headers


def test_a_revoked_token_is_401(live, user_a, session_factory):
    with session_factory() as db:
        db.execute(delete(ApiToken).where(ApiToken.user_id == user_a[0]))
        db.commit()
    assert live.post("/mcp", json=INITIALIZE, headers=headers(user_a[1])).status_code == 401


def test_an_expired_token_is_401(live, user_a, session_factory):
    with session_factory() as db:
        db.execute(update(ApiToken).values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
        db.commit()
    assert live.post("/mcp", json=INITIALIZE, headers=headers(user_a[1])).status_code == 401


def test_a_deactivated_account_is_401(live, user_a, session_factory):
    with session_factory() as db:
        db.execute(update(User).where(User.id == user_a[0]).values(is_active=False))
        db.commit()
    assert live.post("/mcp", json=INITIALIZE, headers=headers(user_a[1])).status_code == 401


def test_the_challenge_carries_the_address_the_client_used(live):
    sent = {**ACCEPT, "Host": "loopback.example", "X-Forwarded-Proto": "https"}
    r = live.post("/mcp", json=INITIALIZE, headers=sent)
    assert r.headers["www-authenticate"] == (
        'Bearer resource_metadata="https://loopback.example/.well-known/oauth-protected-resource/mcp"'
    )


def test_other_paths_are_untouched(live):
    assert live.get("/api/health").status_code == 200
    # A path that merely starts with "mcp" is not the MCP.
    assert live.post("/mcpx", json={}).status_code != 200
