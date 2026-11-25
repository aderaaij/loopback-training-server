"""The coach's fuelling tools: advertised only when nutrition is shared, and
what they ask of the backend."""

import json

import pytest
from fastmcp import Client

from training_mcp import consent as consent_module
from training_mcp import middleware as middleware_module
from training_mcp.consent import NUTRITION, RECOVERY, TRAINING
from training_mcp.main import mcp
from training_mcp.services.api_client import client

pytestmark = pytest.mark.anyio

FUEL_TOOLS = {
    "get_fuel_products",
    "add_fuel_product",
    "get_fuel_history",
    "get_workout_fuel",
    "log_workout_fuel",
    "get_fuel_plan",
    "set_fuel_plan",
}
WORKOUT = "cccccccc-0000-0000-0000-000000000001"
SESSION = "dddddddd-0000-0000-0000-000000000001"
GEL = "eeeeeeee-0000-0000-0000-000000000001"


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
        return {"entries": [], "calls": len(calls)}

    monkeypatch.setattr(client, "_request", _fake)
    shares(TRAINING, NUTRITION)
    return calls


async def _call(tool: str, **args):
    async with Client(mcp) as session:
        result = await session.call_tool(tool, args)
        return json.loads(result.content[0].text)


async def _tools():
    async with Client(mcp) as session:
        return {t.name: t for t in await session.list_tools()}


async def test_fuelling_tools_are_offered_when_nutrition_is_shared(backend):
    assert FUEL_TOOLS <= set(await _tools())


async def test_fuelling_tools_are_not_offered_without_nutrition(backend, shares):
    shares(TRAINING, RECOVERY)
    assert not FUEL_TOOLS & set(await _tools())


async def test_every_fuelling_tool_says_what_it_is_for(backend):
    tools = await _tools()
    for name in FUEL_TOOLS:
        assert len(tools[name].description or "") > 80, name


async def test_products_are_listed(backend):
    await _call("get_fuel_products")
    assert backend == [("GET", "/api/fuel/products", {})]


async def test_a_product_is_saved_with_only_the_figures_given(backend):
    await _call("add_fuel_product", name="Gel 30", kind="gel", carbs_g=30)
    assert backend[-1] == ("POST", "/api/fuel/products", {"name": "Gel 30", "kind": "gel", "carbsG": 30})


async def test_a_workouts_fuelling_is_read(backend):
    await _call("get_workout_fuel", workout_id=WORKOUT)
    assert backend[-1] == ("GET", f"/api/workouts/{WORKOUT}/fuel", {})


async def test_history_is_read_with_its_limit(backend):
    await _call("get_fuel_history", limit=5)
    assert backend[-1] == ("GET", "/api/fuel/history", {"limit": 5})


async def test_logging_adds_each_entry_in_meters(backend):
    result = await _call(
        "log_workout_fuel",
        workout_id=WORKOUT,
        entries=[
            {"name": "Water", "kind": "drink", "volume_ml": 500},
            {"product_id": GEL, "at_distance_m": 7000},
        ],
    )
    assert backend == [
        ("POST", f"/api/workouts/{WORKOUT}/fuel", {"name": "Water", "kind": "drink", "volumeMl": 500}),
        ("POST", f"/api/workouts/{WORKOUT}/fuel", {"productId": GEL, "atDistance": 7000}),
    ]
    # What comes back is the log after the last entry went in.
    assert result["calls"] == 2


async def test_a_log_can_be_replaced_in_one_go(backend):
    await _call(
        "log_workout_fuel",
        workout_id=WORKOUT,
        replace=True,
        entries=[{"name": "Gel", "kind": "gel", "carbs_g": 30, "caffeine_mg": 100, "at_distance_m": 15000}],
    )
    assert backend == [
        (
            "PUT",
            f"/api/workouts/{WORKOUT}/fuel",
            {"entries": [{"name": "Gel", "kind": "gel", "carbsG": 30, "caffeineMg": 100, "atDistance": 15000}]},
        )
    ]


async def test_logging_nothing_is_refused_before_the_backend(backend):
    async with Client(mcp) as session:
        with pytest.raises(Exception):
            await session.call_tool("log_workout_fuel", {"workout_id": WORKOUT, "entries": []})
    assert backend == []


async def test_a_sessions_plan_is_read_and_written(backend):
    await _call("get_fuel_plan", session_id=SESSION)
    assert backend[-1] == ("GET", f"/api/workouts/queue/{SESSION}/fuel", {})

    await _call(
        "set_fuel_plan",
        session_id=SESSION,
        entries=[
            {"name": "Electrolytes", "kind": "drink", "volume_ml": 750},
            {"product_id": GEL, "at_distance_m": 8000},
            {"product_id": GEL, "at_distance_m": 16000},
        ],
    )
    assert backend[-1] == (
        "PUT",
        f"/api/workouts/queue/{SESSION}/fuel",
        {
            "entries": [
                {"name": "Electrolytes", "kind": "drink", "volumeMl": 750},
                {"productId": GEL, "atDistance": 8000},
                {"productId": GEL, "atDistance": 16000},
            ]
        },
    )
