"""The coach's pace calculator: two of distance, time and pace give the third.

Nothing is asked of the backend; what is under test is the arithmetic, the
split table, and that bad input comes back as an error the coach can act on.
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


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def backend(monkeypatch):
    """An athlete sharing only training, and a backend that must stay silent."""
    calls: list[str] = []

    async def _fake(method, path, **kwargs):
        calls.append(path)
        return []

    async def _training_only():
        return frozenset({TRAINING})

    monkeypatch.setattr(client, "_request", _fake)
    monkeypatch.setattr(middleware_module, "shared_domains", _training_only)
    monkeypatch.setattr(consent_module, "shared_domains", _training_only)
    return calls


async def _call(**args):
    async with Client(mcp) as session:
        result = await session.call_tool("calculate_pace", args)
        return json.loads(result.content[0].text)


def _row(result, mark):
    return next(r for r in result["splits"] if r["mark"] == mark)


async def test_the_calculator_is_offered_to_an_athlete_sharing_only_training():
    async with Client(mcp) as session:
        tools = {t.name for t in await session.list_tools()}
    assert "calculate_pace" in tools


async def test_pace_for_a_goal_time(backend):
    result = await _call(race="half_marathon", time="1:45:00")
    assert result["solved_for"] == "pace"
    assert result["distance_m"] == 21097.5
    assert result["distance"] == "21.1 km"
    assert result["time"] == "1:45:00"
    assert result["time_s"] == 6300
    assert result["pace_per_km"] == "4:59"
    assert result["pace_per_km_s"] == 298.6
    assert result["pace_per_mile"] == "8:01"
    assert result["speed_mps"] == 3.349
    assert backend == []


async def test_finish_time_for_a_pace():
    result = await _call(distance_m=10_000, pace="5:00")
    assert result["solved_for"] == "time"
    assert result["time"] == "50:00"
    assert result["time_s"] == 3000


async def test_distance_covered_in_a_time_at_a_pace():
    result = await _call(time="1:00:00", pace="6:00")
    assert result["solved_for"] == "distance"
    assert result["distance_m"] == 10_000
    assert result["distance"] == "10 km"


async def test_time_and_pace_can_be_given_in_seconds():
    assert (await _call(distance_m=5000, time=1500))["pace_per_km"] == "5:00"
    assert (await _call(distance_m=5000, pace=300))["time"] == "25:00"


async def test_an_imperial_pace_is_per_mile():
    result = await _call(race="marathon", pace="8:00", units="imperial")
    # 26.21875 miles at 8:00 each.
    assert result["time"] == "3:29:45"
    assert result["pace_per_mile"] == "8:00"
    assert result["pace_per_km"] == "4:58"
    assert result["distance"] == "26.22 mi"


async def test_a_marathon_reads_as_42_2_km():
    assert (await _call(race="marathon", time="3:30:00"))["distance"] == "42.2 km"


async def test_metric_splits_mark_the_checkpoints_on_their_kilometers():
    result = await _call(race="marathon", time="3:30:00")
    splits = result["splits"]
    # 42 whole km, the half between 21 and 22, and the finish.
    assert len(splits) == 44
    assert _row(result, "5 km")["checkpoint"] == "5K"
    assert _row(result, "30 km")["checkpoint"] == "30K"
    assert "checkpoint" not in _row(result, "6 km")
    assert _row(result, "Half") == {"mark": "Half", "time": "1:45:00", "distance_m": 21097.5}
    assert splits[-1] == {"mark": "Finish", "time": "3:30:00", "distance_m": 42195.0}
    assert [r["mark"] for r in splits[20:23]] == ["21 km", "Half", "22 km"]


async def test_a_race_ending_on_a_whole_kilometer_finishes_on_that_row():
    splits = (await _call(race="10k", time="50:00"))["splits"]
    assert len(splits) == 10
    assert splits[4] == {"mark": "5 km", "time": "25:00", "checkpoint": "5K"}
    assert splits[-1] == {"mark": "10 km", "time": "50:00", "checkpoint": "10K", "finish": True}


async def test_mile_splits_put_the_checkpoints_between_the_miles():
    result = await _call(race="half_marathon", time="1:45:00", units="imperial")
    marks = [r["mark"] for r in result["splits"]]
    assert marks[:5] == ["1 mi", "2 mi", "3 mi", "5K", "4 mi"]
    assert marks[-2:] == ["13 mi", "Finish"]
    assert _row(result, "1 mi")["time"] == "8:01"
    assert _row(result, "5K")["time"] == "24:53"
    assert _row(result, "10K")["time"] == "49:46"
    # The finish is the half marathon mark too.
    assert result["splits"][-1] == {
        "mark": "Finish",
        "time": "1:45:00",
        "checkpoint": "Half",
        "distance_m": 21097.5,
    }


async def test_splits_can_be_cut_down_or_left_out():
    only = await _call(race="marathon", time="3:30:00", splits="checkpoints")
    assert [r["mark"] for r in only["splits"]] == ["5K", "10K", "Half", "30K", "Finish"]
    assert "splits" not in await _call(race="marathon", time="3:30:00", splits="none")


async def test_a_run_shorter_than_one_unit_has_only_a_finish():
    assert (await _call(distance_m=800, time="3:00"))["splits"] == [
        {"mark": "Finish", "time": "3:00", "distance_m": 800.0}
    ]


@pytest.mark.parametrize(
    "args",
    [
        {"race": "10k"},
        {"time": "50:00"},
        {"race": "10k", "time": "50:00", "pace": "5:00"},
        {},
    ],
)
async def test_anything_but_two_of_the_three_is_refused(args):
    assert "exactly two" in (await _call(**args))["error"]


async def test_a_race_and_a_distance_together_are_refused():
    assert "not both" in (await _call(race="10k", distance_m=10_000, time="50:00"))["error"]


@pytest.mark.parametrize("time", ["4:75", "1:60:00", "fast", "1::30", "-5:00", "0:00", 0])
async def test_a_time_that_is_not_a_time_is_refused(time):
    assert "error" in await _call(race="10k", time=time)


async def test_a_distance_of_nothing_is_refused():
    assert "above zero" in (await _call(distance_m=0, time="50:00"))["error"]
