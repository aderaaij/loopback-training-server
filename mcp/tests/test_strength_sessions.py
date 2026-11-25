"""The coach's tools for strength sessions on individual dates.

The backend call is stubbed; what is under test is that the tools are
advertised and what they ask of the backend.
"""

import json

import pytest
from fastmcp import Client

from training_mcp import consent as consent_module
from training_mcp import middleware as middleware_module
from training_mcp.consent import TRAINING
from training_mcp.main import mcp
from training_mcp.services.api_client import client

pytestmark = pytest.mark.anyio

PLAN = "bbbbbbbb-0000-0000-0000-000000000001"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def backend(monkeypatch):
    """Stub the backend and record what was asked of it."""
    calls: list[tuple[str, str, dict]] = []

    async def _fake(method, path, **kwargs):
        calls.append((method, path, kwargs.get("params") or kwargs.get("json") or {}))
        return {"planId": PLAN, "sessions": [], "warnings": []}

    async def _training_only():
        return frozenset({TRAINING})

    monkeypatch.setattr(client, "_request", _fake)
    monkeypatch.setattr(middleware_module, "shared_domains", _training_only)
    monkeypatch.setattr(consent_module, "shared_domains", _training_only)
    return calls


async def _call(tool: str, **args):
    async with Client(mcp) as session:
        result = await session.call_tool(tool, args)
        return json.loads(result.content[0].text)


async def test_session_tools_are_offered(backend):
    async with Client(mcp) as session:
        tools = {t.name for t in await session.list_tools()}
    assert {"add_strength_session", "move_strength_session", "remove_strength_session"} <= tools


async def test_add_sends_the_session_with_its_routine(backend):
    await _call("add_strength_session", plan_id=PLAN, date="2026-12-03", title="Lower", routine_id="hevy-1")
    assert backend[-1] == (
        "POST",
        f"/api/plans/{PLAN}/schedule/sessions",
        {"date": "2026-12-03", "title": "Lower", "routineId": "hevy-1"},
    )


async def test_add_leaves_the_routine_out_when_there_is_none(backend):
    await _call("add_strength_session", plan_id=PLAN, date="2026-12-03", title="Mobility")
    assert backend[-1][2] == {"date": "2026-12-03", "title": "Mobility"}


async def test_move_names_both_days(backend):
    await _call("move_strength_session", plan_id=PLAN, date="2026-12-01", to_date="2026-12-03")
    assert backend[-1] == (
        "POST",
        f"/api/plans/{PLAN}/schedule/sessions/2026-12-01/move",
        {"to": "2026-12-03"},
    )


async def test_remove_names_the_day(backend):
    await _call("remove_strength_session", plan_id=PLAN, date="2026-12-01")
    assert backend[-1] == ("DELETE", f"/api/plans/{PLAN}/schedule/sessions/2026-12-01", {})
