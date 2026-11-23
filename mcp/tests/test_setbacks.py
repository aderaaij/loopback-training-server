"""The coach's setback tools: advertised only when recovery is shared, and
what they ask of the backend."""

import json

import pytest
from fastmcp import Client

from training_mcp import consent as consent_module
from training_mcp import middleware as middleware_module
from training_mcp.consent import RECOVERY, TRAINING
from training_mcp.main import mcp
from training_mcp.services.api_client import client

pytestmark = pytest.mark.anyio

SETBACK_TOOLS = {"get_setbacks", "log_setback", "update_setback", "log_setback_status"}
SID = "bbbbbbbb-0000-0000-0000-000000000001"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def shares(monkeypatch):
    def _set(*domains):
        async def _fake():
            return frozenset(domains)

        monkeypatch.setattr(middleware_module, "shared_domains", _fake)
        monkeypatch.setattr(consent_module, "shared_domains", _fake)

    return _set


@pytest.fixture
def backend(monkeypatch, shares):
    calls: list[tuple[str, str, dict]] = []

    async def _fake(method, path, **kwargs):
        calls.append((method, path, kwargs.get("params") or kwargs.get("json") or {}))
        return {"id": SID}

    monkeypatch.setattr(client, "_request", _fake)
    shares(TRAINING, RECOVERY)
    return calls


async def _call(tool: str, **args):
    async with Client(mcp) as session:
        result = await session.call_tool(tool, args)
        return json.loads(result.content[0].text)


async def _tool_names():
    async with Client(mcp) as session:
        return {t.name for t in await session.list_tools()}


async def test_setback_tools_need_recovery_to_be_shared(shares):
    shares(TRAINING, RECOVERY)
    assert SETBACK_TOOLS <= await _tool_names()

    shares(TRAINING)
    assert not (SETBACK_TOOLS & await _tool_names())


async def test_instructions_name_no_setback_tool():
    """Instructions reach every athlete; the tools are the filtered part."""
    from training_mcp.instructions import build

    text = build("2026-11-23")
    for name in SETBACK_TOOLS:
        assert name not in text, name


async def test_log_setback_sends_only_what_was_given(backend):
    await _call("log_setback", kind="illness", start_date="2026-11-20", note="Flu")
    assert backend == [
        ("POST", "/api/setbacks", {"kind": "illness", "startDate": "2026-11-20", "severity": "moderate", "note": "Flu"})
    ]


async def test_closing_and_reopening(backend):
    await _call("update_setback", setback_id=SID, end_date="2026-11-24")
    await _call("update_setback", setback_id=SID, reopen=True)
    assert backend == [
        ("PATCH", f"/api/setbacks/{SID}", {"endDate": "2026-11-24"}),
        ("PATCH", f"/api/setbacks/{SID}", {"endDate": None}),
    ]


async def test_update_refuses_contradictions_and_empty_calls(backend):
    assert "error" in await _call("update_setback", setback_id=SID, end_date="2026-11-24", reopen=True)
    assert "error" in await _call("update_setback", setback_id=SID)
    assert backend == []


async def test_status_goes_to_the_day_it_describes(backend):
    await _call("log_setback_status", setback_id=SID, status="better", date="2026-11-22", note="fever gone")
    assert backend == [
        ("PUT", f"/api/setbacks/{SID}/checkins/2026-11-22", {"status": "better", "note": "fever gone"})
    ]


async def test_listing_passes_the_filters(backend):
    await _call("get_setbacks", active_only=True, since="2026-11-01")
    await _call("get_setbacks")
    assert backend == [
        ("GET", "/api/setbacks", {"active": "true", "since": "2026-11-01"}),
        ("GET", "/api/setbacks", {}),
    ]
