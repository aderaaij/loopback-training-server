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


def test_build_files_are_served_as_they_are(spa):
    r = TestClient(app).get("/assets/app.js")
    assert r.status_code == 200
    assert "console.log" in r.text


# What an MCP client asks for after the 401 from /mcp. The dashboard's HTML
# with a 200 here is a metadata document the client fails to parse.
@pytest.mark.parametrize(
    "path",
    [
        "/.well-known/oauth-protected-resource",
        "/.well-known/oauth-protected-resource/mcp",
        "/.well-known/oauth-authorization-server",
        "/.well-known/openid-configuration",
    ],
)
def test_well_known_is_404_not_the_dashboard(spa, path):
    r = TestClient(app).get(path)
    assert r.status_code == 404
    assert r.json() == {"detail": "Not Found"}


def test_a_real_well_known_file_is_still_served(spa):
    (spa / ".well-known").mkdir()
    (spa / ".well-known" / "security.txt").write_text("Contact: mailto:security@example.com")
    r = TestClient(app).get("/.well-known/security.txt")
    assert r.status_code == 200
    assert "Contact" in r.text


def test_unknown_api_paths_stay_404(spa):
    assert TestClient(app).get("/api/no-such-thing").status_code == 404
