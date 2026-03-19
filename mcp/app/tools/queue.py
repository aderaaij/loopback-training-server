"""MCP tools for managing the training queue."""

import logging
import uuid

from fastmcp import FastMCP

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
    status: str | None = None,
    limit: int = 50,
) -> dict | list:
    """
    List all queued workouts, including ones already synced to Apple Watch.

    Use this to find the UUID of a workout that has been synced, so you can
    issue edit or delete actions against it.

    Args:
        status: Optional filter — "pending", "fetched", or "completed".
            Omit to return all items regardless of status.
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
    activity_type: str,
    display_name: str,
    location: str,
    scheduled_date: str,
    blocks: list[dict],
    warmup: dict | None = None,
    cooldown: dict | None = None,
    description: str | None = None,
) -> dict | list:
    """
    Create a structured workout composition and queue it for the Apple Watch.

    The workout will appear on the user's Apple Watch via WorkoutKit after
    the iPhone app syncs with the queue.

    Args:
        activity_type: One of "running", "cycling", "walking", "hiking", "swimming".
        display_name: Name shown on Apple Watch (e.g. "6x400m Intervals", "Tempo Run").
        location: Either "outdoor" or "indoor".
        scheduled_date: When the workout should appear, ISO 8601 (e.g. "2026-03-18T07:00:00Z").
        blocks: List of interval blocks. Each block has:
            - iterations (int): Number of times to repeat this block.
            - steps (list): List of interval steps, each with:
                - purpose (str): "work" or "recovery"
                - goal (dict): What defines completion of this step.
                    - type: "distance", "time", "energy", or "open"
                    - value (number): Required for distance/time/energy, omit for open.
                    - unit (str): Required for distance/time.
                      Distance units: "meters", "kilometers", "miles"
                      Time units: "seconds", "minutes"
                      Energy: "kilocalories"
                - alert (dict|null): Optional pacing/effort alert.
                    - type: "speed", "heartRate", "heartRateZone", "cadence", "power", "powerZone"
                    - For speed: min, max, unit ("metersPerSecond" or "kilometersPerHour")
                    - For heartRate: min, max (BPM)
                    - For heartRateZone: zone (1-5)
                    - For cadence: min, max (steps/min)
                    - For power: min, max (watts)
                    - For powerZone: zone (integer)
        warmup: Optional warmup step with same goal/alert structure as an interval step.
        cooldown: Optional cooldown step with same goal/alert structure as an interval step.
        description: Optional text description of the workout.

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
            "blocks": blocks,
            "warmup": warmup,
            "cooldown": cooldown,
        }
        return await client.create_queue_item(
            activity_type=activity_type,
            title=display_name,
            description=description,
            workout_data=workout_data,
        )
    except Exception as e:
        logger.exception(f"Error in create_workout: {e}")
        return {"error": str(e)}


@queue_router.tool
async def update_queued_workout(
    item_id: str,
    display_name: str | None = None,
    activity_type: str | None = None,
    location: str | None = None,
    scheduled_date: str | None = None,
    blocks: list[dict] | None = None,
    warmup: dict | None = None,
    cooldown: dict | None = None,
    description: str | None = None,
) -> dict | list:
    """
    Update an existing queued workout. Only provided fields are changed.

    Use this to reschedule a workout, change the interval structure,
    rename it, or modify any part of the composition before it syncs
    to Apple Watch.

    Args:
        item_id: UUID of the queue item (from get_pending_workouts).
        display_name: New name shown on Apple Watch.
        activity_type: New activity type (running, cycling, etc.).
        location: New location ("outdoor" or "indoor").
        scheduled_date: New scheduled date (ISO 8601).
        blocks: New interval blocks (replaces all existing blocks).
        warmup: New warmup step (use {} to clear, null to leave unchanged).
        cooldown: New cooldown step (use {} to clear, null to leave unchanged).
        description: New text description.

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
            existing_data["blocks"] = blocks
            updated = True
        if warmup is not None:
            existing_data["warmup"] = warmup if warmup != {} else None
            updated = True
        if cooldown is not None:
            existing_data["cooldown"] = cooldown if cooldown != {} else None
            updated = True

        return await client.update_queue_item(
            item_id=item_id,
            activity_type=activity_type,
            title=display_name,
            description=description,
            workout_data=existing_data if updated else None,
        )
    except Exception as e:
        logger.exception(f"Error in update_queued_workout: {e}")
        return {"error": str(e)}


@queue_router.tool
async def update_workout_status(item_id: str, status: str) -> dict | list:
    """
    Update the status of a queue item.

    Args:
        item_id: UUID of the queue item.
        status: New status value (e.g. "pending", "fetched", "completed").
                Setting to "fetched" records the fetch timestamp.
                Setting to "completed" records the completion timestamp.

    Returns:
        The updated queue item object.
    """
    try:
        return await client.update_queue_status(item_id=item_id, status=status)
    except Exception as e:
        logger.exception(f"Error in update_workout_status: {e}")
        return {"error": str(e)}


@queue_router.tool
async def batch_create_workouts(workouts: list[dict]) -> dict | list:
    """
    Queue multiple workouts for Apple Watch in a single call.

    Use this instead of calling create_workout repeatedly when you need to
    schedule an entire training plan (e.g. 4 weeks of workouts).

    Args:
        workouts: List of workout objects. Each must have:
            - activityType (str): "running", "cycling", "walking", "hiking", or "swimming".
            - title (str): Display name (e.g. "Tempo Run").
            - description (str|null): Optional text description.
            - workoutData (dict): Full workout composition with:
                - id (str): A unique UUID (generate one per workout).
                - displayName (str): Name shown on Apple Watch.
                - activityType (str): Same as above.
                - location (str): "outdoor" or "indoor".
                - scheduledDate (str): ISO 8601 date.
                - blocks (list): Interval blocks.
                - warmup (dict|null): Optional warmup step.
                - cooldown (dict|null): Optional cooldown step.

    Example:
        workouts: [
            {
                "activityType": "running",
                "title": "Easy 5K",
                "workoutData": {
                    "id": "unique-uuid-1",
                    "displayName": "Easy 5K",
                    "activityType": "running",
                    "location": "outdoor",
                    "scheduledDate": "2026-03-20T07:00:00Z",
                    "blocks": [{"iterations": 1, "steps": [{"purpose": "work",
                        "goal": {"type": "distance", "value": 5000, "unit": "meters"}}]}]
                }
            }
        ]

    Returns:
        List of created queue items.
    """
    try:
        return await client.create_queue_items_batch(workouts)
    except Exception as e:
        logger.exception(f"Error in batch_create_workouts: {e}")
        return {"error": str(e)}
