"""get_missed_workouts: which past-due runs still need a check-in.

The backend calls are stubbed; the logic under test is the cross-reference of
the device inventory against feedback, in particular for moved runs.
"""

from datetime import date, timedelta

import pytest

from app.services.api_client import client

WORKOUT_ID = "11111111-1111-1111-1111-111111111111"


def _day(offset: int) -> date:
    return date.today() + timedelta(days=offset)


def _inventory_item(day: date) -> dict:
    return {
        "id": WORKOUT_ID,
        "display_name": "Long Run 9k",
        "year": day.year,
        "month": day.month,
        "day": day.day,
        "complete": False,
    }


def _feedback(action: str, scheduled: date, new_date: date | None = None, dismissed: bool = False) -> dict:
    return {
        "workoutId": WORKOUT_ID,
        "scheduledDate": f"{scheduled.isoformat()}T07:00:00Z",
        "action": action,
        "newDate": f"{new_date.isoformat()}T07:00:00Z" if new_date else None,
        "dismissed": dismissed,
    }


@pytest.fixture
def backend(monkeypatch):
    """Serve this inventory and feedback from the stubbed backend."""

    def _set(inventory: list[dict], feedback: list[dict]):
        async def _fake(method, path, **kwargs):
            return inventory if path.endswith("/inventory") else feedback

        monkeypatch.setattr(client, "_request", _fake)

    return _set


async def test_run_without_feedback_is_missed(backend):
    backend([_inventory_item(_day(-1))], [])
    missed = await client.get_missed_workouts()
    assert [m["workoutId"] for m in missed] == [WORKOUT_ID]
    assert missed[0]["daysMissed"] == 1


async def test_skipped_run_is_settled(backend):
    backend([_inventory_item(_day(-2))], [_feedback("skip", _day(-2))])
    assert await client.get_missed_workouts() == []


async def test_dismissed_move_still_settles(backend):
    backend([_inventory_item(_day(-2))], [_feedback("move", _day(-3), new_date=_day(-2), dismissed=True)])
    assert await client.get_missed_workouts() == []


async def test_moved_run_missed_on_its_new_day_is_missed_again(backend):
    backend([_inventory_item(_day(-1))], [_feedback("move", _day(-3), new_date=_day(-1))])
    missed = await client.get_missed_workouts()
    assert [m["workoutId"] for m in missed] == [WORKOUT_ID]


async def test_moved_run_on_stale_inventory_day_is_settled(backend):
    # The move went through but the device inventory still shows the old day.
    backend([_inventory_item(_day(-1))], [_feedback("move", _day(-1), new_date=_day(1))])
    assert await client.get_missed_workouts() == []


async def test_run_moved_ahead_of_time_is_not_due_yet(backend):
    backend([_inventory_item(_day(1))], [_feedback("move", _day(0), new_date=_day(1))])
    assert await client.get_missed_workouts() == []
