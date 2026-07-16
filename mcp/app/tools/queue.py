"""MCP tools for managing the training queue."""

import logging
import uuid

from fastmcp import FastMCP

from app.schemas import (
    ActivityType,
    BatchWorkoutItem,
    IntervalBlock,
    IsoDateTime,
    Location,
    QueueStatus,
    WorkoutStep,
    dump_step,
)
from app.services.api_client import client

logger = logging.getLogger(__name__)

queue_router = FastMCP(name="Queue Tools")


@queue_router.tool
async def get_pending_workouts() -> dict | list:
    """
    Get all pending workout queue items waiting to be processed.

    Returns:
        List of pending queue items, each with: id, activity_type, title,
        description, workout_data, status, created_at, fetched_at, completed_at.
    """
    try:
        return await client.get_pending_queue()
    except Exception as e:
        logger.exception(f"Error in get_pending_workouts: {e}")
        return {"error": str(e)}


@queue_router.tool
async def list_queued_workouts(
    status: QueueStatus | None = None,
    limit: int = 50,
) -> dict | list:
    """
    List all queued workouts, including ones already synced to Apple Watch.

    Use this to find the UUID of a workout that has been synced, so you can
    issue edit or delete actions against it.

    Args:
        status: Optional filter — "pending", "fetched", "synced",
            "completed", or "skipped". Omit to return all items.
        limit: Max number of items to return (default 50, max 200).

    Returns:
        List of queue items sorted by creation date (newest first), each with:
        id, activity_type, title, description, workout_data, status,
        created_at, fetched_at, completed_at.
    """
    try:
        return await client.list_queue(status=status, limit=limit)
    except Exception as e:
        logger.exception(f"Error in list_queued_workouts: {e}")
        return {"error": str(e)}


@queue_router.tool
async def create_workout(
    activity_type: ActivityType,
    display_name: str,
    location: Location,
    scheduled_date: IsoDateTime,
    blocks: list[IntervalBlock],
    warmup: WorkoutStep | None = None,
    cooldown: WorkoutStep | None = None,
    description: str | None = None,
    plan_id: str | None = None,
) -> dict | list:
    """
    Create a structured workout and queue it for the user's Apple Watch.

    Full WorkoutKit support: repeatable interval blocks, warmup/cooldown steps,
    goals (distance / time / energy / open), and an optional per-step ALERT that
    coaches effort on the watch — pace/speed range, heart-rate range (BPM),
    heart-rate ZONE (1-5), cadence, or running power. E.g. a Zone 2 base run is
    a single time- or distance-goal step with alert
    {"type": "heartRateZone", "zone": 2}. WorkoutKit allows one alert per step.

    The exact structure of blocks/steps/goals/alerts is defined in this tool's
    input schema. The workout appears on the watch after the iPhone app syncs.

    Args:
        activity_type: Sport for the WorkoutKit session.
        display_name: Name shown on Apple Watch (e.g. "6x400m Intervals", "Tempo Run").
        location: Where the workout happens (affects GPS).
        scheduled_date: When the workout should appear, ISO 8601 (e.g. "2026-03-18T07:00:00Z").
        blocks: Interval blocks, each repeated `iterations` times.
        warmup: Optional warmup step (goal + optional alert).
        cooldown: Optional cooldown step (goal + optional alert).
        description: Optional text description of the workout.
        plan_id: Optional UUID of the training plan this workout belongs to.

    Returns:
        The created queue item object.

    Example — 6x400m intervals with 800m warmup and cooldown:
        activity_type: "running"
        display_name: "6x400m Intervals"
        location: "outdoor"
        scheduled_date: "2026-03-18T07:00:00Z"
        warmup: {"goal": {"type": "distance", "value": 800, "unit": "meters"}}
        blocks: [
            {
                "iterations": 6,
                "steps": [
                    {
                        "purpose": "work",
                        "goal": {"type": "distance", "value": 400, "unit": "meters"},
                        "alert": {"type": "speed", "min": 4.5, "max": 5.0, "unit": "metersPerSecond"}
                    },
                    {
                        "purpose": "recovery",
                        "goal": {"type": "distance", "value": 400, "unit": "meters"}
                    }
                ]
            }
        ]
        cooldown: {"goal": {"type": "distance", "value": 800, "unit": "meters"}}

    Example — 20-minute tempo run:
        activity_type: "running"
        display_name: "20min Tempo"
        location: "outdoor"
        scheduled_date: "2026-03-19T07:00:00Z"
        warmup: {"goal": {"type": "distance", "value": 1600, "unit": "meters"}}
        blocks: [
            {
                "iterations": 1,
                "steps": [
                    {
                        "purpose": "work",
                        "goal": {"type": "time", "value": 20, "unit": "minutes"},
                        "alert": {"type": "heartRateZone", "zone": 4}
                    }
                ]
            }
        ]
        cooldown: {"goal": {"type": "distance", "value": 1600, "unit": "meters"}}
    """
    try:
        workout_data = {
            "id": str(uuid.uuid4()),
            "displayName": display_name,
            "activityType": activity_type,
            "location": location,
            "scheduledDate": scheduled_date,
            "blocks": [b.model_dump(exclude_none=True) for b in blocks],
            "warmup": dump_step(warmup),
            "cooldown": dump_step(cooldown),
        }
        return await client.create_queue_item(
            activity_type=activity_type,
            title=display_name,
            description=description,
            workout_data=workout_data,
            plan_id=plan_id,
        )
    except Exception as e:
        logger.exception(f"Error in create_workout: {e}")
        return {"error": str(e)}


@queue_router.tool
async def update_queued_workout(
    item_id: str,
    display_name: str | None = None,
    activity_type: ActivityType | None = None,
    location: Location | None = None,
    scheduled_date: IsoDateTime | None = None,
    blocks: list[IntervalBlock] | None = None,
    warmup: WorkoutStep | None = None,
    cooldown: WorkoutStep | None = None,
    clear_warmup: bool = False,
    clear_cooldown: bool = False,
    description: str | None = None,
    plan_id: str | None = None,
) -> dict | list:
    """
    Update an existing queued workout. Only provided fields are changed.

    Use this to reschedule a workout, change the interval structure,
    rename it, or modify any part of the composition before it syncs
    to Apple Watch. Steps support the same goals and alerts (incl.
    heart-rate zones) as create_workout — see that tool's input schema.

    Args:
        item_id: UUID of the queue item (from get_pending_workouts).
        display_name: New name shown on Apple Watch.
        activity_type: New activity type (running, cycling, etc.).
        location: New location ("outdoor" or "indoor").
        scheduled_date: New scheduled date (ISO 8601).
        blocks: New interval blocks (replaces all existing blocks).
        warmup: New warmup step (omit to leave unchanged).
        cooldown: New cooldown step (omit to leave unchanged).
        clear_warmup: Set true to remove the existing warmup.
        clear_cooldown: Set true to remove the existing cooldown.
        description: New text description.
        plan_id: UUID of the training plan to assign this workout to.

    Returns:
        The updated queue item object.
    """
    try:
        # First fetch the current item to get existing workout_data
        current = await client.get_pending_queue()
        existing_data = {}
        for item in current if isinstance(current, list) else []:
            if str(item.get("id")) == item_id:
                existing_data = dict(item.get("workout_data") or {})
                break

        # Update workout_data fields
        updated = False
        if display_name is not None:
            existing_data["displayName"] = display_name
            updated = True
        if activity_type is not None:
            existing_data["activityType"] = activity_type
            updated = True
        if location is not None:
            existing_data["location"] = location
            updated = True
        if scheduled_date is not None:
            existing_data["scheduledDate"] = scheduled_date
            updated = True
        if blocks is not None:
            existing_data["blocks"] = [b.model_dump(exclude_none=True) for b in blocks]
            updated = True
        if warmup is not None or clear_warmup:
            existing_data["warmup"] = dump_step(warmup)
            updated = True
        if cooldown is not None or clear_cooldown:
            existing_data["cooldown"] = dump_step(cooldown)
            updated = True

        return await client.update_queue_item(
            item_id=item_id,
            activity_type=activity_type,
            title=display_name,
            description=description,
            workout_data=existing_data if updated else None,
            plan_id=plan_id,
        )
    except Exception as e:
        logger.exception(f"Error in update_queued_workout: {e}")
        return {"error": str(e)}


@queue_router.tool
async def update_workout_status(item_id: str, status: QueueStatus) -> dict | list:
    """
    Update the status of a queue item.

    Lifecycle: pending -> fetched -> synced -> completed. "skipped" retires
    the item (the watch endpoints stop serving it and it no longer counts as
    a schedule collision) — normally set via missed-workout feedback with
    action "skip", but it can be set directly here too.

    Args:
        item_id: UUID of the queue item.
        status: New status. Setting "fetched" records the fetch timestamp;
                "completed" records the completion timestamp.

    Returns:
        The updated queue item object.
    """
    try:
        return await client.update_queue_status(item_id=item_id, status=status)
    except Exception as e:
        logger.exception(f"Error in update_workout_status: {e}")
        return {"error": str(e)}


@queue_router.tool
async def batch_create_workouts(workouts: list[BatchWorkoutItem]) -> dict | list:
    """
    Queue multiple workouts for Apple Watch in a single call.

    Use this instead of calling create_workout repeatedly when you need to
    schedule an entire training plan (e.g. 4 weeks of workouts). Each workout
    supports the same full composition as create_workout: interval blocks,
    warmup/cooldown, goals (distance/time/energy/open), and per-step alerts —
    pace/speed range, heart-rate range, heart-rate zone (1-5), cadence, power.

    Args:
        workouts: Workouts to queue — see the input schema for the full
            structure. Omit workoutData.id to have a UUID generated per
            workout. Set planId to link a workout to a training plan.

    Example:
        workouts: [
            {
                "activityType": "running",
                "title": "Easy Z2 5K",
                "workoutData": {
                    "displayName": "Easy Z2 5K",
                    "activityType": "running",
                    "location": "outdoor",
                    "scheduledDate": "2026-03-20T07:00:00Z",
                    "blocks": [{"iterations": 1, "steps": [{"purpose": "work",
                        "goal": {"type": "distance", "value": 5000, "unit": "meters"},
                        "alert": {"type": "heartRateZone", "zone": 2}}]}]
                }
            }
        ]

    Returns:
        List of created queue items.
    """
    try:
        items: list[dict] = []
        for w in workouts:
            comp = w.workoutData
            if comp.id is None:
                comp = comp.model_copy(update={"id": str(uuid.uuid4())})
            body: dict = {
                "activityType": w.activityType,
                "title": w.title,
                "workoutData": comp.wire_dict(),
            }
            if w.description is not None:
                body["description"] = w.description
            if w.planId is not None:
                body["planId"] = w.planId
            items.append(body)
        return await client.create_queue_items_batch(items)
    except Exception as e:
        logger.exception(f"Error in batch_create_workouts: {e}")
        return {"error": str(e)}
