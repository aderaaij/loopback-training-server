"""Training MCP Server - Main entry point."""

import logging
from datetime import date

from fastmcp import FastMCP

from app.config import settings
from app.tools.actions import actions_router
from app.tools.queue import queue_router
from app.tools.workouts import workouts_router

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)

mcp = FastMCP(
    "training-mcp",
    instructions=f"""
    Today's date is {date.today().isoformat()}.

    Provides access to workout tracking data and a training queue for planning workouts.
    This is a single-user system — no user discovery step is needed.

    Available tools:

    Read tools (workout history):
    - get_recent_runs: List recent workouts with optional filters (activity type, date range, limit)
    - get_workout_detail: Get full details for a specific workout by ID
    - get_workout_splits: Get per-split breakdown for a workout (e.g. per-km pace)
    - get_workout_heartrate: Get heart rate samples recorded during a workout
    - get_workout_activities: Get the interval/segment breakdown (warmup, work, rest periods)
    - get_training_summary: Get aggregated stats grouped by week/month/year

    Write tools (training queue → Apple Watch):
    - get_pending_workouts: See what workouts are queued up (pending only)
    - list_queued_workouts: List all queued workouts (any status) — use this to find the UUID of a synced workout for edit/delete actions
    - create_workout: Create a structured workout composition and queue it for Apple Watch
    - batch_create_workouts: Queue multiple workouts in one call (for full training plans)
    - update_workout_status: Change a queue item's status (pending/fetched/completed)

    Action tools (edit/delete workouts already on Apple Watch):
    - get_device_workouts: List all workouts currently on the user's Apple Watch (use to find UUIDs for edit/delete)
    - get_pending_actions: See what edit/delete actions are pending
    - delete_scheduled_workout: Delete a workout already synced to Apple Watch
    - edit_scheduled_workout: Replace a workout already synced to Apple Watch with an updated version
    - batch_actions: Create multiple edit/delete actions in one call (for bulk plan updates)

    Workflow for querying workout history:
    1. Determine the date range from the user's question:
       - "last week" → start_after = 7 days ago, start_before = today
       - "this month" → start_after = first of month, start_before = today
       - No time specified → default to last 2 weeks
    2. Call get_recent_runs with appropriate filters
    3. For deeper detail on a specific workout, use get_workout_detail, get_workout_splits,
       get_workout_heartrate, or get_workout_activities with the workout's ID
    4. Use get_workout_activities to see the interval structure (warmup/work/rest segments)
       — this is especially useful for interval runs and structured workouts

    Workflow for editing/deleting workouts already on Apple Watch:
    1. First call get_device_workouts to see what's on the watch and find the UUID.
    2. To delete: use delete_scheduled_workout with the workout's UUID.
    3. To edit: use edit_scheduled_workout with the workout's UUID and the full updated composition.
       The composition.id must match the workout_id.
    4. Actions are applied the next time the user taps "Check for New Workouts" in the iPhone app.
    5. Use get_pending_actions to see what actions are pending.

    Workflow for creating workouts:
    1. Use create_workout to build a structured workout composition. This queues it
       for the iPhone app, which syncs it to the Apple Watch via WorkoutKit.
    2. Structure: warmup (optional) → interval blocks (work/recovery steps with
       iterations) → cooldown (optional). Each step has a goal (distance/time/open)
       and optional alerts (pace, heart rate zone, cadence, power).
    3. Use get_pending_workouts to review what's queued and waiting to sync.

    Common activity types: running, cycling, swimming, walking, hiking
    Distance is in meters, duration in seconds, energy in kcal.
    Speed alerts use metersPerSecond (e.g., 4:00/km pace ≈ 4.17 m/s, 5:00/km ≈ 3.33 m/s).
    """,
)

mcp.mount(workouts_router)
mcp.mount(queue_router)
mcp.mount(actions_router)

logger.info(f"Training MCP server initialized. API URL: {settings.training_api_url}")


def main() -> None:
    """Entry point for the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
