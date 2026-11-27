"""The SPA catch-all: which paths get the dashboard and which get a 404.

The suite normally runs without a frontend build, where the catch-all answers
404 for everything, so these point it at a throwaway build directory.
"""

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app


@pytest.fixture()
def spa(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<!doctype html><title>Loopback</title>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log('app')")
    monkeypatch.setattr(main_module, "SPA_DIST", tmp_path)
    monkeypatch.setattr(main_module, "SPA_INDEX", tmp_path / "index.html")
    return tmp_path


def test_client_side_routes_get_the_dashboard(spa):
    r = TestClient(app).get("/workouts/123")
    assert r.status_code == 200
    assert "Loopback" in r.text


# Another site must not be able to show the dashboard inside its own page,
# least of all the page where an assistant is approved.
@pytest.mark.parametrize("path", ["/", "/workouts/123", "/oauth/consent?request=abc"])
def test_the_dashboard_refuses_to_be_framed(spa, path):
    r = TestClient(app).get(path)
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["content-security-policy"] == "frame-ancestors 'none'"


def test_build_files_are_served_as_they_are(spa):
    r = TestClient(app).get("/assets/app.js")
    assert r.status_code == 200
    assert "console.log" in r.text


# Programs read /.well-known, not people. The dashboard's HTML with a 200 is a
# document they fail to parse, where a 404 says "nothing of that kind here".
@pytest.mark.parametrize(
    "path",
    [
        # Where an MCP client looks for a second kind of OAuth metadata when
        # the first (below) is missing.
        "/.well-known/openid-configuration",
        "/.well-known/oauth-protected-resource/other",
        "/.well-known/anything-else.json",
    ],
)
def test_well_known_is_404_not_the_dashboard(spa, path):
    r = TestClient(app).get(path)
    assert r.status_code == 404
    assert r.json() == {"detail": "Not Found"}


# The OAuth metadata an MCP client asks for after the 401 from /mcp is served
# by routes of its own (routes/oauth.py), which have to win over the catch-all.
@pytest.mark.parametrize(
    "path",
    [
        "/.well-known/oauth-protected-resource",
        "/.well-known/oauth-protected-resource/mcp",
        "/.well-known/oauth-authorization-server",
    ],
)
def test_oauth_metadata_is_json_not_the_dashboard(spa, path):
    r = TestClient(app).get(path)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/json"
    assert "Loopback</title>" not in r.text


# The approval page is the dashboard's; the two endpoints beside it are not.
def test_the_approval_page_is_the_dashboard(spa):
    r = TestClient(app).get("/oauth/consent?request=abc")
    assert r.status_code == 200
    assert "Loopback" in r.text


def test_a_real_well_known_file_is_still_served(spa):
    (spa / ".well-known").mkdir()
    (spa / ".well-known" / "security.txt").write_text("Contact: mailto:security@example.com")
    r = TestClient(app).get("/.well-known/security.txt")
    assert r.status_code == 200
    assert "Contact" in r.text


def test_unknown_api_paths_stay_404(spa):
    assert TestClient(app).get("/api/no-such-thing").status_code == 404


# A proxy that publishes only the coach forwards by prefix, so these reach
# the server from the internet. None of them is a dashboard page.
@pytest.mark.parametrize(
    "path",
    ["/mcp/api/health", "/mcp//api/health", "/mcp/anything", "/oauth/token/x", "/oauth/authorize/x"],
)
def test_paths_under_the_coach_endpoints_are_not_the_dashboard(spa, path):
    r = TestClient(app).get(path)
    assert r.status_code == 404
    assert "Loopback" not in r.text
