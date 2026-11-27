"""The Claude Desktop extension (.mcpb) for the coach, built on request.

Claude Desktop cannot send a bearer token to a remote MCP server by itself,
and its connector dialog goes through Anthropic's servers, which cannot reach
a server on a private network. An extension is the way in that needs neither
Node.js nor a hand-edited config file: Claude Desktop installs the bundle,
runs it with the Node it ships, asks for the settings in a form and keeps the
token in the OS keychain.

The bundle is a zip of `app/desktop_extension/` (a manifest and one
dependency-free script that relays stdio to /mcp), assembled here rather than
at image build time so the server address can be filled in for whoever
downloads it. The token is deliberately not filled in: the file sits in a
downloads folder and gets passed around, and with a token inside, whoever
installs it would act as the athlete it was made for.
"""

import io
import json
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

SOURCE_DIR = Path(__file__).resolve().parent / "desktop_extension"
FILENAME = "loopback-coach.mcpb"

# Fixed, so the same version and address always give the same bytes.
_ZIP_DATE = (2026, 1, 1, 0, 0, 0)


def clean_server_url(raw: str | None) -> str | None:
    """The origin to prefill, or None for no prefill. Raises ValueError for
    anything that is not a plain http(s) address."""
    if raw is None or not raw.strip():
        return None
    parts = urlsplit(raw.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise ValueError("serverUrl must be an http:// or https:// address")
    return f"{parts.scheme}://{parts.netloc}"


def build_manifest(version: str, server_url: str | None = None) -> dict:
    manifest = json.loads((SOURCE_DIR / "manifest.json").read_text(encoding="utf-8"))
    manifest["version"] = version
    if server_url:
        manifest["user_config"]["server_url"]["default"] = server_url
    return manifest


def build_bundle(version: str, server_url: str | None = None) -> bytes:
    manifest = json.dumps(build_manifest(version, server_url), indent=2, ensure_ascii=False) + "\n"
    files: dict[str, bytes] = {"manifest.json": manifest.encode("utf-8")}
    for path in sorted(SOURCE_DIR.rglob("*")):
        relative = path.relative_to(SOURCE_DIR)
        if not path.is_file() or relative.as_posix() == "manifest.json":
            continue
        # Editor droppings and macOS AppleDouble files (`._name`) stay out.
        if any(part.startswith(".") or part == "__pycache__" for part in relative.parts):
            continue
        files[relative.as_posix()] = path.read_bytes()

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            info = zipfile.ZipInfo(name, date_time=_ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)
    return buffer.getvalue()
