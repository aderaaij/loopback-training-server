"""Training MCP Server - Main entry point."""

import logging
import os
from datetime import date

from fastmcp import FastMCP

from app.config import settings
from app.tools.actions import actions_router
from app.tools.feedback import feedback_router
from app.tools.health_metrics import health_metrics_router
from app.tools.plan_notes import plan_notes_router
from app.tools.plans import plans_router
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
    Data is scoped to the authenticated user — no user discovery step is needed.

    CONTINUITY (read this first):
    The user discusses their training across MANY separate conversations. To make
    each one feel like a continuation rather than a cold start:
      1. At the START of any training-related conversation, call `get_plan_context`
         BEFORE answering. It returns the active plan, recent decisions/preferences/
         constraints/life-context, and a `continuity_hint` directive. Read the hint.
      2. DURING the conversation, call `append_plan_note` without being asked when
         the user reveals: a preference ("I prefer", "from now on"), a decision
         ("let's drop", "I've decided"), life context (travel, illness, sleep
         debt, work stress), a hard constraint, or a non-obvious insight.
         Err on the side of saving — short notes are cheap.
      3. Use a stable `conversation_id` for all notes saved in one conversation
         so future-you can see what was discussed together.

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

    Plan tools (training plan management):
    - create_plan: Create a new training plan with metadata (goals, guardrails, phases)
    - get_plan: Get a plan by ID with full metadata
    - list_plans: List plans (filter by status, activity_type)
    - update_plan: Update plan fields (name, status, metadata, end_date)
    - get_plan_workouts: Get all queued workouts belonging to a plan

    Plan continuity tools (cross-conversation memory — see CONTINUITY note above):
    - get_plan_context: Active plan + recent notes + continuity hint. Call FIRST.
    - append_plan_note: Save a decision/preference/constraint/life_context/observation/blocker.
      Call without being asked when the user reveals plan-relevant info.
    - list_plan_notes: Targeted retrieval (filter by kind, conversation, etc.)
    - update_plan_note: Correct or refine an existing note.
    - delete_plan_note: Remove an incorrect/duplicate note (prefer update or expires_at).

    Workflow for creating a training plan:
    1. Use create_plan to store the plan entity with goals, guardrails, phases, and
       athlete context in the metadata blob. Get back the plan_id.
    2. Use batch_create_workouts (or create_workout) with plan_id set on each workout
       to link them to the plan.
    3. When querying progress, use get_plan to load context, then get_plan_workouts
       to see scheduled workouts, then cross-reference with recorded workouts via
       plan_workout_id to compute completion rates and planned-vs-actual.

    Workflow for creating workouts:
    1. Use create_workout to build a structured workout composition. This queues it
       for the iPhone app, which syncs it to the Apple Watch via WorkoutKit.
    2. Structure: warmup (optional) → interval blocks (work/recovery steps with
       iterations) → cooldown (optional). Each step has a goal (distance/time/open)
       and optional alerts (pace, heart rate zone, cadence, power).
    3. Use get_pending_workouts to review what's queued and waiting to sync.
    4. Always pass plan_id when creating workouts that belong to a plan.

    Feedback tools (missed workout feedback from iOS app):
    - get_workout_feedback: Retrieve feedback entries for missed workouts (filter by date, action type)
    - get_missed_workouts: Get past-due incomplete workouts that don't yet have feedback

    Workflow for missed workout feedback:
    - Query get_workout_feedback with action="adjust" to find workouts flagged for plan adjustment.
      When found, proactively raise with the user: "Looks like you missed X and flagged it for
      adjustment — want to figure out how to handle it?"
    - action="move" means the user already rescheduled — no action needed, just note for patterns.
    - action="skip" means the user chose to skip — only surface if a pattern emerges (e.g. 3+ skips
      with reason "tired" → suggest reducing volume).
    - dismissed=true means the user closed the prompt without responding — treat like skip with less signal.
    - Use get_missed_workouts to find workouts that are overdue and haven't been addressed yet.
    - During weekly reviews, look for patterns: multiple "tired" → reduce volume, multiple "busy" →
      shift workout days, multiple "weather" → suggest indoor alternatives.

    Health metrics tools (daily HealthKit data synced from iPhone):
    - get_health_metrics: Query daily health metrics (sleep, resting HR, HRV, weight, VO2Max,
      steps, active energy, body fat, lean body mass, respiratory rate, SpO2)

    Use health metrics to correlate recovery/readiness with training patterns. For example:
    - Low HRV + poor sleep → suggest easier workout or rest day
    - Declining resting HR trend → improving cardiovascular fitness
    - Weight/body composition trends alongside training volume

    Common activity types: running, cycling, swimming, walking, hiking
    Distance is in meters, duration in seconds, energy in kcal.
    Speed alerts use metersPerSecond (e.g., 4:00/km pace ≈ 4.17 m/s, 5:00/km ≈ 3.33 m/s).
    """,
)

mcp.mount(workouts_router)
mcp.mount(queue_router)
mcp.mount(actions_router)
mcp.mount(feedback_router)
mcp.mount(health_metrics_router)
mcp.mount(plans_router)
mcp.mount(plan_notes_router)

logger.info(f"Training MCP server initialized. API URL: {settings.training_api_url}")


def main() -> None:
    """Entry point for the MCP server.

    Default transport is stdio (direct clients, or wrapped by supergateway).
    Set MCP_TRANSPORT=http (with MCP_HOST / MCP_PORT) to serve streamable HTTP
    natively — no supergateway needed; point clients at http://<host>:<port>/mcp
    """
    transport = os.environ.get("MCP_TRANSPORT", "stdio").lower()
    if transport in ("http", "streamable-http"):
        mcp.run(
            transport="http",
            host=os.environ.get("MCP_HOST", "0.0.0.0"),
            port=int(os.environ.get("MCP_PORT", "8590")),
        )
    else:
        mcp.run()


if __name__ == "__main__":
    main()
