"""Runtime map-tile config: precedence of the settings, and the endpoint.

CARTO_API_KEY is a convenience over MAP_TILE_URL, and the unset case must
keep the original look — so each rung of that ladder is pinned here.
"""

from app.config import Settings, get_settings
from app.main import app

URL = "/api/config"
DB = "postgresql+psycopg://u:p@localhost/db"
LEGACY = "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, database_url=DB, **kw)


def test_defaults_keep_the_current_look():
    tiles = _settings().map_tiles
    assert tiles["tileUrl"] == LEGACY
    assert tiles["subdomains"] == "abcd"
    assert "CARTO" in tiles["attribution"]


def test_carto_key_builds_the_documented_keyed_url():
    url = _settings(carto_api_key="abc 123").map_tiles["tileUrl"]
    assert url == "https://basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}{r}.png?key=abc%20123"


def test_explicit_url_beats_the_carto_key():
    tpl = "https://tiles.example.com/{z}/{x}/{y}.png?token=t"
    tiles = _settings(
        map_tile_url=tpl,
        carto_api_key="k",
        map_tile_attribution="&copy; Example",
        map_tile_subdomains="ab",
    ).map_tiles
    assert tiles == {"tileUrl": tpl, "attribution": "&copy; Example", "subdomains": "ab"}


def test_endpoint_requires_auth(client_a):
    from fastapi.testclient import TestClient

    assert TestClient(app).get(URL).status_code == 401
    assert client_a.get(URL).status_code == 200


def test_endpoint_serves_the_settings(client_a):
    app.dependency_overrides[get_settings] = lambda: _settings(carto_api_key="k")
    body = client_a.get(URL).json()
    assert body["map"]["tileUrl"].endswith("?key=k")
    assert set(body) == {"map", "coachUrl"}
    assert set(body["map"]) == {"tileUrl", "attribution", "subdomains"}


# The dashboard shows an assistant the address it was itself opened at, unless
# the server was told its public one: an assistant in the cloud needs that one.
def test_coach_address_is_only_given_when_the_server_was_told_it(client_a, monkeypatch):
    assert client_a.get(URL).json()["coachUrl"] is None
    monkeypatch.setattr(get_settings(), "public_url", "https://coach.example")
    assert client_a.get(URL).json()["coachUrl"] == "https://coach.example/mcp"


# With the dashboard on a port of its own next to a coach on the standard one
# (deploy/tailscale), the coach's address is the dashboard's without the port.
def test_coach_address_follows_the_dashboard_when_only_the_port_differs(client_a, monkeypatch):
    monkeypatch.setattr(get_settings(), "oauth_authorization_port", 8443)
    headers = {"Host": "loopback.tailnet.example:8443", "X-Forwarded-Proto": "https"}
    assert client_a.get(URL, headers=headers).json()["coachUrl"] == "https://loopback.tailnet.example/mcp"
