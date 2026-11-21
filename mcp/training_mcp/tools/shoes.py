"""MCP tools for the athlete's running shoes."""

import logging
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from training_mcp.services.api_client import client
from training_mcp.wire import text_result

logger = logging.getLogger(__name__)

shoes_router = FastMCP(name="Shoe Tools")


@shoes_router.tool
@text_result
async def get_shoes(include_retired: bool = True) -> dict | list:
    """
    List the athlete's pairs of running shoes and the distance on each.

    CHECKING THE PAIR ON RECENT RUNS. A new run is put on the default pair
    automatically, and the athlete often forgets to correct it when they wore
    something else. Workouts carry `shoe_confirmed`: false means the pair was
    never checked. When the athlete has MORE THAN ONE pair in rotation and a
    run from the last two weeks has `shoe_confirmed: false`, ask which pair
    they wore — once per conversation, all such runs in one question, naming
    each run's day, distance and current pair. Then call assign_shoe for every
    run they answer, including the ones where the current pair was right:
    that is what marks it checked and stops the question coming back. Skip
    the question when only one pair is in rotation, for older runs, and for
    anything that is not a run.

    Args:
        include_retired: Include pairs the athlete has put away (default true).
                         Pass false for only the pairs in rotation.

    Returns:
        List of pairs, in use first (newest first), then retired. Keys are
        camelCase and every distance is in METERS:

        - id: matches `shoe_id` on a workout (get_recent_runs,
          get_workout_detail). Pass it to get_recent_runs as `shoe_id` to list
          the runs done in this pair.
        - name: what the athlete called the pair.
        - distance: total on the pair — `startDistance` plus every workout
          assigned to it.
        - startDistance: what the pair had on it when it was added. That part
          is the athlete's own figure, not recorded runs.
        - targetDistance: where the athlete plans to replace the pair, or null
          when they set none. Their choice, not a wear measurement.
        - workoutCount / lastUsedAt: assigned workouts and the latest one's
          start. Zero and null for a pair with no runs on it yet.
        - isDefault: new runs land on this pair automatically. At most one.
        - retiredAt: when the pair was put away, null while in rotation.
        - createdAt: when the pair was added to the app, not when it was bought.

        A run with `shoe_id: null` has no pair recorded, which is common: runs
        from before the athlete added a pair are never assigned, and walks,
        rides and strength sessions never get one automatically. Null does not
        mean barefoot, and a pair's `distance` only counts what was assigned.
    """
    try:
        shoes = await client.list_shoes()
        if not include_retired and isinstance(shoes, list):
            shoes = [s for s in shoes if not s.get("retiredAt")]
        return shoes
    except Exception as e:
        logger.exception(f"Error in get_shoes: {e}")
        return {"error": str(e)}


@shoes_router.tool
@text_result
async def add_shoe(
    name: Annotated[str, Field(min_length=1, max_length=120)],
    start_distance_meters: Annotated[float, Field(ge=0)] = 0,
    target_distance_meters: Annotated[float | None, Field(gt=0)] = None,
    is_default: bool = False,
) -> dict | list:
    """
    Add a pair of running shoes for the athlete.

    Only on the athlete's say-so: they tell you about a new pair, you add it.
    Check get_shoes first so the same pair is not added twice.

    Args:
        name: What to call the pair, in the athlete's words (e.g. "Pegasus 41").
        start_distance_meters: Distance already on the pair, in METERS
            (250 km is 250000). Zero for a new pair. Runs from before the pair
            is added are never assigned to it, so this figure is where that
            earlier distance belongs.
        target_distance_meters: Where the athlete plans to replace the pair,
            in METERS. Leave out unless they named one — do not pick a figure
            for them.
        is_default: Put new runs on this pair automatically. Replaces the
            current default.

    Returns:
        The new pair, in the shape get_shoes lists.
    """
    try:
        shoe: dict[str, Any] = {
            "name": name,
            "startDistance": start_distance_meters,
            "isDefault": is_default,
        }
        if target_distance_meters is not None:
            shoe["targetDistance"] = target_distance_meters
        return await client.create_shoe(shoe)
    except Exception as e:
        logger.exception(f"Error in add_shoe: {e}")
        return {"error": str(e)}


@shoes_router.tool
@text_result
async def update_shoe(
    shoe_id: str,
    name: Annotated[str | None, Field(min_length=1, max_length=120)] = None,
    start_distance_meters: Annotated[float | None, Field(ge=0)] = None,
    target_distance_meters: Annotated[float | None, Field(gt=0)] = None,
    clear_target: bool = False,
    is_default: bool | None = None,
    retired: bool | None = None,
) -> dict | list:
    """
    Change a pair of shoes: rename it, correct its distances, make it the
    default, retire it or bring it back. Only what you pass changes.

    There is no tool to delete a pair; that stays in the app. Retire a pair
    the athlete has stopped using — its runs and distance are kept.

    Args:
        shoe_id: The pair's id from get_shoes.
        name: New name.
        start_distance_meters: Distance the pair had before it was added, in
            METERS. This is not the pair's total: the total is this plus its
            assigned runs, so to correct a total, work out the difference.
        target_distance_meters: New replacement distance, in METERS.
        clear_target: True removes the replacement distance. Do not combine
            with target_distance_meters.
        is_default: True makes this the pair new runs land on (replacing the
            current default); false leaves the athlete with no default. A
            retired pair cannot be the default.
        retired: True puts the pair away (it also stops being the default);
            false brings it back into rotation.

    Returns:
        The updated pair, in the shape get_shoes lists.
    """
    try:
        if clear_target and target_distance_meters is not None:
            return {"error": "Pass either target_distance_meters or clear_target, not both."}
        changes: dict[str, Any] = {}
        if name is not None:
            changes["name"] = name
        if start_distance_meters is not None:
            changes["startDistance"] = start_distance_meters
        if target_distance_meters is not None:
            changes["targetDistance"] = target_distance_meters
        if clear_target:
            changes["targetDistance"] = None
        if is_default is not None:
            changes["isDefault"] = is_default
        if retired is not None:
            changes["retired"] = retired
        if not changes:
            return {"error": "Nothing to change: pass at least one field besides shoe_id."}
        return await client.update_shoe(shoe_id, changes)
    except Exception as e:
        logger.exception(f"Error in update_shoe: {e}")
        return {"error": str(e)}


@shoes_router.tool
@text_result
async def assign_shoe(workout_id: str, shoe_id: str | None = None) -> dict | list:
    """
    Put a pair of shoes on a workout, or take the pair off.

    Use it when the athlete says which pair they wore. It also marks the
    workout's pair as checked (`shoe_confirmed: true`), so call it even when
    the athlete confirms the pair already on the run. Never guess a pair from
    the kind of session: ask.

    Args:
        workout_id: UUID of the recorded workout (from get_recent_runs).
        shoe_id: The pair's id from get_shoes. A retired pair is fine, for
            correcting an older run. Leave out to take the pair off the
            workout, for a run done in shoes the athlete does not track.

    Returns:
        The workout as get_recent_runs lists it, with the new shoe_id.
    """
    try:
        return await client.set_workout_shoe(workout_id, shoe_id)
    except Exception as e:
        logger.exception(f"Error in assign_shoe: {e}")
        return {"error": str(e)}
