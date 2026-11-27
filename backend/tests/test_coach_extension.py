"""The Claude Desktop extension download (GET /api/coach/claude-desktop.mcpb).

The relay script inside the bundle has its own suite, run with Node
(tests/desktop_extension), which also starts it the way Claude Desktop does.
These cover what the server puts in the zip.
"""

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

import app.routes.coach as coach_module
from app.coach_extension import build_bundle, clean_server_url
from app.main import app
from app.version import __version__

URL = "/api/coach/claude-desktop.mcpb"


def _unzip(content: bytes) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(content))


def _manifest(content: bytes) -> dict:
    return json.loads(_unzip(content).read("manifest.json"))


def test_download_needs_a_token():
    assert TestClient(app).get(URL).status_code == 401


def test_bundle_is_an_installable_extension(client_a):
    r = client_a.get(URL)
    assert r.status_code == 200, r.text
    assert 'filename="loopback-coach.mcpb"' in r.headers["content-disposition"]

    archive = _unzip(r.content)
    # Claude Desktop looks for the manifest at the root of the zip.
    assert set(archive.namelist()) == {"manifest.json", "package.json", "server/index.js", "server/relay.js"}
    manifest = _manifest(r.content)
    assert manifest["version"] == __version__
    assert manifest["server"]["entry_point"] == "server/index.js"
    assert manifest["user_config"]["token"]["sensitive"] is True
    assert "default" not in manifest["user_config"]["server_url"]


def test_server_address_is_filled_in_from_the_dashboard_origin(client_a):
    # The dashboard sends the address it is open at; only the origin is kept.
    r = client_a.get(URL, params={"serverUrl": "https://loopback.example.com:8443/settings?tab=coach"})
    assert r.status_code == 200
    assert _manifest(r.content)["user_config"]["server_url"]["default"] == "https://loopback.example.com:8443"


@pytest.mark.parametrize(
    "bad",
    ["javascript:alert(1)", "ftp://example.com", "example.com:8001", "https://user:pw@example.com", "https://"],
)
def test_other_addresses_are_refused(client_a, bad):
    assert client_a.get(URL, params={"serverUrl": bad}).status_code == 422


def test_the_token_is_never_in_the_bundle(client_a, user_a):
    # The file ends up in a downloads folder and gets passed on; with a token
    # inside, whoever installs it would act as this athlete.
    content = client_a.get(URL, params={"serverUrl": "http://my-server:8001"}).content
    token = user_a[1].encode()
    archive = _unzip(content)
    assert all(token not in archive.read(name) for name in archive.namelist())
    assert "default" not in _manifest(content)["user_config"]["token"]


def test_no_download_when_the_coach_is_switched_off(client_a, monkeypatch):
    monkeypatch.setattr(coach_module, "MCP_ENABLED", False)
    assert client_a.get(URL).status_code == 404


def test_manifest_and_script_agree_on_the_settings():
    # The manifest hands the settings to the script as environment variables;
    # a rename on one side only would leave the extension unconfigured.
    archive = _unzip(build_bundle("1.2.3"))
    manifest = json.loads(archive.read("manifest.json"))
    script = archive.read("server/relay.js").decode()
    env = manifest["server"]["mcp_config"]["env"]
    assert set(env.values()) == {"${user_config.server_url}", "${user_config.token}"}
    for name in env:
        assert f"env.{name}" in script


def test_same_input_gives_the_same_bytes():
    assert build_bundle("1.2.3", "https://a.example") == build_bundle("1.2.3", "https://a.example")


def test_blank_address_means_no_prefill():
    assert clean_server_url(None) is None
    assert clean_server_url("   ") is None
