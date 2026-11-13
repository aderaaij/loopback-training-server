"""The unauthenticated health endpoint — the iOS app's version handshake."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.version import __version__


def test_health_reports_version():
    resp = TestClient(app).get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "training-api"
    assert body["version"] == __version__
    assert body["database"] == "ok"


@pytest.mark.parametrize("enabled", [True, False])
def test_health_reports_whether_the_coach_endpoint_is_served(monkeypatch, enabled):
    # The dashboard hides its "connect your coach" setup when this is false.
    # Patched where the route reads it: health.py imports the value by name.
    monkeypatch.setattr("app.routes.health.MCP_ENABLED", enabled)

    assert TestClient(app).get("/api/health").json()["mcp"] is enabled
