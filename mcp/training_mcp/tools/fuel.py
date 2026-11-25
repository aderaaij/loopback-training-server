"""MCP tools for fuelling: what the athlete drinks and eats on a workout, and
the plan for a session ahead.

Advertised only to an athlete who shares `nutrition` with the coach (see
training_mcp/consent.py), so the guidance lives here on the tools and not in
the server instructions, which every athlete's client reads.

Separate from get_nutrition, which is daily totals read from Health. This is
entered by hand, by the athlete in the app or by the coach on their say-so,
and belongs to one workout or one planned session.
"""

import logging
from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from training_mcp.services.api_client import client
from training_mcp.wire import text_result

logger = logging.getLogger(__name__)

fuel_router = FastMCP(name="Fuelling Tools")

FuelKind = Literal["drink", "gel", "other"]


class FuelEntry(BaseModel):
    """One thing drunk or eaten, or planned to be."""

    product_id: str | None = Field(
        default=None,
        description="A saved product's id from get_fuel_products. Its name, kind, carbohydrates and "
        "caffeine are filled in from it (for a drink, in proportion to volume_ml), so with a product "
        "only volume_ml or at_distance_m is needed.",
    )
    name: str | None = Field(default=None, description="What it was. Required without a product_id.")
    kind: FuelKind | None = Field(
        default=None,
        description='"drink" for anything drunk, logged as ONE entry with the total volume; "gel" for a '
        'gel; "other" for anything else eaten or swallowed (chews, a bar, a salt tablet). Required '
        "without a product_id.",
    )
    volume_ml: float | None = Field(default=None, description="For a drink: the total over the workout, in ml.")
    carbs_g: float | None = Field(default=None, description="Carbohydrates in this entry as a whole, in g.")
    caffeine_mg: float | None = Field(default=None, description="Caffeine in this entry as a whole, in mg.")
    at_distance_m: float | None = Field(
        default=None,
        description="Where in the workout it was (or is to be) taken, in METERS from the start: 7000 for "
        "km 7. For a gel or other item; leave out for a drink, and when the athlete does not know.",
    )

    def wire(self) -> dict[str, Any]:
        keys = {
            "product_id": "productId",
            "name": "name",
            "kind": "kind",
            "volume_ml": "volumeMl",
            "carbs_g": "carbsG",
            "caffeine_mg": "caffeineMg",
            "at_distance_m": "atDistance",
        }
        return {wire: getattr(self, field) for field, wire in keys.items() if getattr(self, field) is not None}


@fuel_router.tool
@text_result
async def get_fuel_products() -> dict | list:
    """
    List what the athlete has saved to drink and eat on runs: their gels,
    drink mixes and so on.

    Call this before writing a fuelling plan, so the plan names what the
    athlete actually carries and its figures are the label's, not yours.

    Returns:
        List of products (camelCase), drinks first: id (pass as product_id in
        an entry), name, kind, carbsG and caffeineMg (per piece; for a drink,
        per serving of volumeMl), volumeMl (a drink's serving, null
        otherwise). Null carbsG or caffeineMg means the athlete did not state
        it, not zero.
    """
    try:
        return await client.list_fuel_products()
    except Exception as e:
        logger.exception(f"Error in get_fuel_products: {e}")
        return {"error": str(e)}


@fuel_router.tool
@text_result
async def add_fuel_product(
    name: str,
    kind: FuelKind,
    carbs_g: Annotated[float | None, Field(ge=0, le=1000)] = None,
    caffeine_mg: Annotated[float | None, Field(ge=0, le=1000)] = None,
    volume_ml: Annotated[float | None, Field(gt=0, le=5000)] = None,
) -> dict | list:
    """
    Save something the athlete drinks or eats on runs, so it can be picked
    when logging or planning.

    Only on the athlete's say-so, with figures they gave you or read off the
    label. Do not fill in carbohydrates or caffeine from memory of a brand;
    leave a figure out when the athlete does not know it. Check
    get_fuel_products first so nothing is saved twice.

    Args:
        name: What the athlete calls it ("Maurten Gel 100 Caf", "Water").
        kind: "drink", "gel" or "other" (chews, a bar, a salt tablet).
        carbs_g: Carbohydrates in g, per piece, or per serving of a drink.
        caffeine_mg: Caffeine in mg, per piece, or per serving of a drink.
        volume_ml: For a drink only: the serving the two figures are for, in
            ml (500 for a 500 ml bottle).

    Returns:
        The saved product, in the shape get_fuel_products lists.
    """
    try:
        product: dict[str, Any] = {"name": name, "kind": kind}
        if carbs_g is not None:
            product["carbsG"] = carbs_g
        if caffeine_mg is not None:
            product["caffeineMg"] = caffeine_mg
        if volume_ml is not None:
            product["volumeMl"] = volume_ml
        return await client.create_fuel_product(product)
    except Exception as e:
        logger.exception(f"Error in add_fuel_product: {e}")
        return {"error": str(e)}


@fuel_router.tool
@text_result
async def get_fuel_history(limit: Annotated[int, Field(ge=1, le=50)] = 10) -> dict | list:
    """
    The athlete's most recent workouts that have a fuelling log, newest
    first, each with what was taken and what had been planned for it.

    Read this before planning the fuelling for a long run or a race: it shows
    what the athlete has actually been taking, how much per hour, and whether
    they kept to earlier plans. To see how a run went against its fuelling,
    look the workout up with get_workout_detail or get_workout_splits (a fade
    late in the run next to few carbohydrates per hour is the pattern to look
    for). A workout that is not listed has no log, which usually means the
    athlete did not write it down, not that they took nothing.

    Args:
        limit: How many workouts (default 10, at most 50).

    Returns:
        List (camelCase) of: workoutId, activityType, startDate, duration
        (seconds), totalDistance (METERS), entries and summary (taken),
        planned and plannedSummary (the plan on the session the workout
        counted for; empty and null when there was none), plannedSessionId.
        Entries and summaries are as get_workout_fuel describes them.
    """
    try:
        return await client.get_fuel_history(limit)
    except Exception as e:
        logger.exception(f"Error in get_fuel_history: {e}")
        return {"error": str(e)}


@fuel_router.tool
@text_result
async def get_workout_fuel(workout_id: str) -> dict | list:
    """
    What the athlete drank and ate on one workout, next to what was planned
    for it.

    Use it when reviewing a long run or a race, and whenever the athlete
    brings up fuelling, a fade, stomach trouble or cramping on a run. An empty
    `entries` usually means nothing was written down, not that nothing was
    taken: ask before concluding anything from it.

    Args:
        workout_id: UUID of the workout (from get_recent_runs).

    Returns:
        Object (camelCase) with entries and summary (what was taken), planned
        and plannedSummary (the plan on the session this workout counted for;
        empty and null when there was none), plannedSessionId.

        Each entry (camelCase): id, productId (null when typed in by hand or
        the product was deleted since), name, kind ("drink", "gel", "other"),
        volumeMl (a drink's total), carbsG and caffeineMg (in the entry as a
        whole; null means not stated, NOT zero), atDistance (METERS into the
        workout, null for a drink or when not placed). Drinks come first, then
        the rest in the order taken.

        A summary (camelCase): volumeMl, carbsG, caffeineMg, and
        carbsPerHourG / fluidPerHourMl over the workout's duration. An entry
        without a figure counts as zero, so treat a total as a floor when an
        entry has null carbsG. The hourly rates are null for a workout under
        20 minutes and for a plan on its own.
    """
    try:
        return await client.get_workout_fuel(workout_id)
    except Exception as e:
        logger.exception(f"Error in get_workout_fuel: {e}")
        return {"error": str(e)}


@fuel_router.tool
@text_result
async def log_workout_fuel(
    workout_id: str,
    entries: Annotated[list[FuelEntry], Field(min_length=1, max_length=50)],
    replace: bool = False,
) -> dict | list:
    """
    Write down what the athlete drank and ate on a workout, on their say-so.

    The athlete can log this in the app themselves; use this when they tell
    you in conversation instead ("I had two gels and a bottle of water on
    Sunday's long run"). Log what they say, not what was planned, and ask
    rather than guess when they are vague about an amount. A drink is ONE
    entry with the total volume; each gel is its own entry, with
    at_distance_m when they remember where they took it.

    Args:
        workout_id: UUID of the workout (from get_recent_runs).
        entries: What to log. Prefer product_id (get_fuel_products) so the
            figures are the athlete's own.
        replace: False (default) adds to what is already logged. True
            replaces the whole log with `entries`; use it to correct a log,
            after reading it with get_workout_fuel.

    Returns:
        The workout's fuelling afterwards, in the shape get_workout_fuel
        returns.
    """
    try:
        if replace:
            return await client.set_workout_fuel(workout_id, [e.wire() for e in entries])
        result: dict | list = {}
        for entry in entries:
            result = await client.add_workout_fuel(workout_id, entry.wire())
        return result
    except Exception as e:
        logger.exception(f"Error in log_workout_fuel: {e}")
        return {"error": str(e)}


@fuel_router.tool
@text_result
async def get_fuel_plan(session_id: str) -> dict | list:
    """
    The fuelling plan on a planned session: what to drink and eat, and where
    in the run.

    Args:
        session_id: UUID of the planned session, the queue item's id (from
            get_plan_workouts, get_pending_workouts or list_queued_workouts).

    Returns:
        Object (camelCase) with entries and summary, as get_workout_fuel
        describes them. Empty entries means no plan has been written for this
        session.
    """
    try:
        return await client.get_session_fuel(session_id)
    except Exception as e:
        logger.exception(f"Error in get_fuel_plan: {e}")
        return {"error": str(e)}


@fuel_router.tool
@text_result
async def set_fuel_plan(
    session_id: str,
    entries: Annotated[list[FuelEntry], Field(max_length=50)],
) -> dict | list:
    """
    Write the fuelling plan for a planned session. It replaces any plan the
    session already has; an empty list removes it.

    The athlete sees the plan on the session in the app, and after the run
    next to what they logged, where one tap logs it as planned. So write the
    plan you would want them to follow, item by item, not a general remark:
    that belongs in the conversation or the session's description.

    BEFORE WRITING ONE: get_fuel_products for what the athlete carries, and
    get_fuel_history for what they have taken on earlier long runs and how
    much per hour. Build on that; a plan far above what they are used to is
    one their stomach has not practised. Say in the conversation what the
    plan adds up to per hour and why.

    One entry per drink with the total to drink over the run (volume_ml), and
    one entry per gel or other item with where to take it (at_distance_m,
    METERS). Use product_id wherever the athlete has the product saved.

    This is not medical advice, and caffeine and sodium tolerance are
    personal: where the athlete has not used something before, say so and
    suggest trying it in training first.

    Args:
        session_id: UUID of the planned session, the queue item's id (from
            get_plan_workouts, get_pending_workouts or list_queued_workouts).
        entries: The whole plan.

    Returns:
        The session's plan afterwards, in the shape get_fuel_plan returns.
    """
    try:
        return await client.set_session_fuel(session_id, [e.wire() for e in entries])
    except Exception as e:
        logger.exception(f"Error in set_fuel_plan: {e}")
        return {"error": str(e)}
