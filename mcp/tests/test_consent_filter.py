"""The consent filter, exercised through a real MCP session.

Driven with FastMCP's in-memory client so the middleware chain runs exactly as
it does over HTTP: tools/list returns the tools the athlete's client would
actually see. Asserting against the middleware in isolation would prove nothing
about whether it is wired in.

The consent lookup itself is stubbed — the point here is the filtering, not the
HTTP call to the backend (whose own filtering has its own suite).
"""

import pytest

from app import consent as consent_module
from app import middleware as middleware_module
from app.consent import ACTIVITY, ALL_DOMAINS, NUTRITION, TRAINING
from app.main import mcp

pytestmark = pytest.mark.anyio

METRIC_TOOL = "get_health_metrics"
NUTRITION_TOOLS = {"get_nutrition", "get_nutrition_summary"}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def shares(monkeypatch):
    """Pretend the caller shares exactly these domains."""

    def _set(*domains):
        async def _fake():
            return frozenset(domains)

        # Patched where it is used, not only where it is defined.
        monkeypatch.setattr(middleware_module, "shared_domains", _fake)
        monkeypatch.setattr(consent_module, "shared_domains", _fake)

    return _set


async def _tools():
    from fastmcp import Client

    async with Client(mcp) as client:
        return {t.name: t for t in await client.list_tools()}


async def test_everything_shared_advertises_everything(shares):
    shares(*ALL_DOMAINS)
    tools = await _tools()
    assert METRIC_TOOL in tools
    assert NUTRITION_TOOLS <= set(tools)


async def test_training_only_hides_every_health_tool(shares):
    shares(TRAINING)
    tools = await _tools()

    assert METRIC_TOOL not in tools
    assert not (NUTRITION_TOOLS & set(tools))
    # Training tooling is untouched — an athlete who shares nothing else still
    # shares workouts, or there is no history to coach from.
    assert {"get_recent_runs", "create_workout", "get_plan_context"} <= set(tools)


async def test_one_metric_domain_keeps_the_shared_row_tool(shares):
    """recovery/body/activity are columns of one row, so one is enough.

    The backend then drops the unshared columns from the payload — the tool
    surviving is not the same as the whole row surviving.
    """
    shares(TRAINING, ACTIVITY)
    tools = await _tools()

    assert METRIC_TOOL in tools
    assert not (NUTRITION_TOOLS & set(tools))


async def test_nutrition_alone_keeps_only_the_nutrition_tools(shares):
    shares(TRAINING, NUTRITION)
    tools = await _tools()

    assert NUTRITION_TOOLS <= set(tools)
    assert METRIC_TOOL not in tools


async def test_a_lookup_failure_advertises_everything(monkeypatch):
    """A backend blip must not silently strip a working coach of its context.

    In a real outage every data tool fails anyway, so there is nothing to
    disclose; failing closed would just look like amnesia.
    """

    async def _boom():
        raise RuntimeError("backend down")

    monkeypatch.setattr(middleware_module, "shared_domains", _boom)
    tools = await _tools()
    assert METRIC_TOOL in tools
    assert NUTRITION_TOOLS <= set(tools)


async def test_instructions_describe_no_health_tooling(shares):
    """Instructions are fixed when the connection opens, so they are read by
    every athlete regardless of what they share. Domain guidance therefore
    belongs on the tools (which ARE filtered) — if it creeps back in here, an
    athlete who shares nothing still gets told about nutrition tooling."""
    from app.instructions import build

    text = build("2026-07-31")
    for absent in ("Health metrics tools", "Nutrition tools", "get_nutrition",
                   "get_health_metrics", "Energy balance", "balance_kcal_avg"):
        assert absent not in text, absent


async def test_domain_guidance_survives_on_the_tools(shares):
    """Moving it out of the instructions must not have lost it."""
    shares(*ALL_DOMAINS)
    tools = await _tools()

    summary = tools["get_nutrition_summary"].description or ""
    assert "double-counts" in summary or "double-count" in summary
    assert "LOWER BOUND" in summary
    assert "not a dietitian" in summary
    metrics = tools[METRIC_TOOL].description or ""
    assert "Low HRV + poor sleep" in metrics


def test_tool_map_survives_a_mount_prefix():
    """Names are matched on the suffix too, so mounting a router under a
    prefix later can't quietly turn the filter into a no-op."""
    from app.consent import tool_is_shared

    for name in (METRIC_TOOL, f"health_{METRIC_TOOL}"):
        assert tool_is_shared(name, frozenset({ACTIVITY}))
        assert not tool_is_shared(name, frozenset({TRAINING, NUTRITION}))
