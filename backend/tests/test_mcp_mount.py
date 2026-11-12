"""The coach MCP is served from the API's own port at /mcp.

These cover the wiring only — that a client reaches a live MCP at the bare
path and that the door asks for credentials. Tool behaviour is covered by the
MCP's own suite (mcp/tests), which runs against FastMCP's in-memory transport.
"""

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app

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
HEADERS = {
    "Authorization": "Bearer tapi_anything",
    "Accept": "application/json, text/event-stream",
}


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
def test_initialize_reaches_the_mcp(live, path):
    r = live.post(path, json=INITIALIZE, headers=HEADERS)
    assert r.status_code == 200, r.text
    assert "training-mcp" in r.text
    assert r.headers.get("mcp-session-id")


@pytest.mark.parametrize("auth", [None, "Basic abc", "Bearer"])
def test_no_bearer_token_is_401(live, auth):
    headers = {"Accept": HEADERS["Accept"]}
    if auth:
        headers["Authorization"] = auth
    r = live.post("/mcp", json=INITIALIZE, headers=headers)
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"
    assert "Create token" in r.json()["detail"]


def test_other_paths_are_untouched(live):
    assert live.get("/api/health").status_code == 200
    # A path that merely starts with "mcp" is not the MCP.
    assert live.post("/mcpx", json={}).status_code != 200
