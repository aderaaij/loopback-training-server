"""The coach's shoe tools: listing pairs, changing them, assigning them to runs.

The backend call is stubbed; what is under test is that the tools are
advertised whatever the athlete shares, and what they ask of the backend.
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

IN_USE = {"id": "aaaaaaaa-0000-0000-0000-000000000001", "name": "Pegasus 41", "distance": 412_300.0, "retiredAt": None}
RETIRED = {
    "id": "aaaaaaaa-0000-0000-0000-000000000002",
    "name": "Vaporfly 3",
    "distance": 655_000.0,
    "retiredAt": "2026-10-01T08:00:00Z",
}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def backend(monkeypatch):
    """Stub the backend and record what was asked of it."""
    calls: list[tuple[str, str, dict]] = []

    async def _fake(method, path, **kwargs):
        calls.append((method, path, kwargs.get("params") or kwargs.get("json") or {}))
        return [IN_USE, RETIRED] if path == "/api/shoes" else []

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


async def test_shoes_are_offered_to_an_athlete_sharing_only_training(backend):
    async with Client(mcp) as session:
        tools = {t.name for t in await session.list_tools()}
    assert {"get_shoes", "add_shoe", "update_shoe", "assign_shoe"} <= tools


async def test_every_pair_is_listed_by_default(backend):
    assert await _call("get_shoes") == [IN_USE, RETIRED]


async def test_retired_pairs_can_be_left_out(backend):
    assert await _call("get_shoes", include_retired=False) == [IN_USE]


async def test_runs_can_be_asked_for_by_pair(backend):
    await _call("get_recent_runs", shoe_id=IN_USE["id"])
    assert backend[-1] == ("GET", "/api/workouts", {"limit": 10, "shoe_id": IN_USE["id"]})


async def test_a_pair_is_added_in_meters(backend):
    await _call("add_shoe", name="Novablast 5", start_distance_meters=120_000, is_default=True)
    assert backend[-1] == (
        "POST",
        "/api/shoes",
        {"name": "Novablast 5", "startDistance": 120_000, "isDefault": True},
    )


async def test_only_the_fields_given_are_changed(backend):
    await _call("update_shoe", shoe_id=IN_USE["id"], retired=True)
    assert backend[-1] == ("PATCH", f"/api/shoes/{IN_USE['id']}", {"retired": True})


async def test_the_target_can_be_removed(backend):
    await _call("update_shoe", shoe_id=IN_USE["id"], clear_target=True)
    assert backend[-1] == ("PATCH", f"/api/shoes/{IN_USE['id']}", {"targetDistance": None})


async def test_an_empty_change_never_reaches_the_backend(backend):
    result = await _call("update_shoe", shoe_id=IN_USE["id"])
    assert "error" in result
    assert backend == []


async def test_a_pair_is_put_on_a_workout(backend):
    await _call("assign_shoe", workout_id="w-1", shoe_id=IN_USE["id"])
    assert backend[-1] == ("PUT", "/api/workouts/w-1/shoe", {"shoeId": IN_USE["id"]})
