"""MCP tools for managing workout actions (edit/delete scheduled workouts)."""

import logging

from fastmcp import FastMCP

from app.schemas import (
    ActivityType,
    IntervalBlock,
    Location,
    WorkoutActionItem,
    WorkoutStep,
    dump_step,
)
from app.services.api_client import client

logger = logging.getLogger(__name__)

actions_router = FastMCP(name="Action Tools")


@actions_router.tool
async def get_device_workouts() -> dict | list:
    """
    Get the inventory of workouts currently scheduled on the user's Apple Watch.

    This is synced from the iOS app each time the user taps "Check for New Workouts".
    Use this to discover workout UUIDs when the user asks to edit or delete a workout.

    Returns:
        List of on-device workouts, each with: id, display_name, year, month, day,
        hour, minute, complete (whether the workout has been done), synced_at.
    """
    try:
        return await client.get_inventory()
    except Exception as e:
        logger.exception(f"Error in get_device_workouts: {e}")
        return {"error": str(e)}


@actions_router.tool
async def get_pending_actions() -> dict | list:
    """
    Get all pending workout actions (edits and deletes) waiting to be synced to Apple Watch.

    Returns:
        List of pending actions, each with: id, workoutId, action ("edit" or "delete"),
        composition (full workout composition for edits, null for deletes), created_at.
    """
    try:
        return await client.get_pending_actions()
    except Exception as e:
        logger.exception(f"Error in get_pending_actions: {e}")
        return {"error": str(e)}


@actions_router.tool
async def delete_scheduled_workout(workout_id: str) -> dict | list:
    """
    Delete a workout that has already been synced to the user's Apple Watch.

    Creates a pending delete action. The next time the iPhone app syncs,
    it will remove this workout from WorkoutKit on the Apple Watch.

    Args:
        workout_id: UUID of the workout to delete. This is the id from the
            original queue item that was synced to the watch.

    Returns:
        The created action object.
    """
    try:
        return await client.create_action(
            workout_id=workout_id,
            action="delete",
        )
    except Exception as e:
        logger.exception(f"Error in delete_scheduled_workout: {e}")
        return {"error": str(e)}


@actions_router.tool
async def edit_scheduled_workout(
    workout_id: str,
    display_name: str,
    activity_type: ActivityType,
    location: Location,
    scheduled_date: str,
    blocks: list[IntervalBlock],
    warmup: WorkoutStep | None = None,
    cooldown: WorkoutStep | None = None,
) -> dict | list:
    """
    Edit a workout that has already been synced to the user's Apple Watch.

    Creates a pending edit action with the full updated composition. The next
    time the iPhone app syncs, it will replace the old workout with this
    updated version in WorkoutKit on the Apple Watch. Steps support the same
    goals and alerts as create_workout — pace/speed range, heart-rate range,
    heart-rate zone (1-5), cadence, power — see the input schema.

    Args:
        workout_id: UUID of the workout to edit. Must match the id from the
            original queue item that was synced to the watch.
        display_name: Updated name shown on Apple Watch.
        activity_type: Sport for the WorkoutKit session.
        location: Either "outdoor" or "indoor".
        scheduled_date: Updated scheduled date, ISO 8601 (e.g. "2026-03-25T07:00:00Z").
        blocks: Updated interval blocks (replaces the whole structure).
        warmup: Optional updated warmup step.
        cooldown: Optional updated cooldown step.

    Returns:
        The created action object.
    """
    try:
        composition = {
            "id": workout_id,
            "displayName": display_name,
            "activityType": activity_type,
            "location": location,
            "scheduledDate": scheduled_date,
            "blocks": [b.model_dump(exclude_none=True) for b in blocks],
            "warmup": dump_step(warmup),
            "cooldown": dump_step(cooldown),
        }
        return await client.create_action(
            workout_id=workout_id,
            action="edit",
            composition=composition,
        )
    except Exception as e:
        logger.exception(f"Error in edit_scheduled_workout: {e}")
        return {"error": str(e)}


@actions_router.tool
async def batch_actions(actions: list[WorkoutActionItem]) -> dict | list:
    """
    Create multiple edit/delete actions in a single call.

    Use this instead of calling delete_scheduled_workout or edit_scheduled_workout
    repeatedly when you need to modify or remove multiple workouts at once.
    Edit compositions support the same goals and per-step alerts as
    create_workout (incl. heart-rate zones) — see the input schema.

    Args:
        actions: Action objects. For "edit", composition is the full
            replacement workout (composition.id may be omitted — it is filled
            from workoutId). For "delete", omit composition.

    Example:
        actions: [
            {"workoutId": "aaa-...", "action": "delete"},
            {"workoutId": "bbb-...", "action": "edit", "composition": {
                "displayName": "Updated Run", "activityType": "running",
                "location": "outdoor", "scheduledDate": "2026-03-25T07:00:00Z",
                "blocks": [{"iterations": 1, "steps": [{"purpose": "work",
                    "goal": {"type": "time", "value": 1800, "unit": "seconds"},
                    "alert": {"type": "heartRateZone", "zone": 3}}]}]
            }}
        ]

    Returns:
        List of created action objects.
    """
    try:
        payload: list[dict] = []
        for a in actions:
            body: dict = {"workoutId": a.workoutId, "action": a.action}
            if a.composition is not None:
                comp = a.composition
                if comp.id is None:
                    comp = comp.model_copy(update={"id": a.workoutId})
                body["composition"] = comp.wire_dict()
            payload.append(body)
        return await client.create_actions_batch(payload)
    except Exception as e:
        logger.exception(f"Error in batch_actions: {e}")
        return {"error": str(e)}
