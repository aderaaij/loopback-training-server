"""MCP tools for querying workout data."""

import logging

from fastmcp import FastMCP

from training_mcp.schemas import SummaryPeriod
from training_mcp.services.api_client import client
from training_mcp.wire import text_result

logger = logging.getLogger(__name__)

workouts_router = FastMCP(name="Workout Tools")


@workouts_router.tool
@text_result
async def get_recent_runs(
    activity_type: str | None = None,
    limit: int = 10,
    start_after: str | None = None,
    start_before: str | None = None,
    shoe_id: str | None = None,
) -> dict | list:
    """
    List recent workouts, optionally filtered by activity type, date range and
    the pair of shoes they were done in.

    Args:
        activity_type: Filter by activity type (e.g. "running", "cycling", "swimming").
                       If omitted, returns all activity types.
        limit: Maximum number of workouts to return (default 10, max 200).
        start_after: Only return workouts starting after this datetime (ISO 8601).
                     Example: "2026-03-01T00:00:00"
        start_before: Only return workouts starting before this datetime (ISO 8601).
                      Example: "2026-03-15T23:59:59"
        shoe_id: Only return workouts done in this pair of shoes (an id from
                 get_shoes).

    Returns:
        List of workout objects with fields: id, activity_type, start_date, end_date,
        duration, total_distance, total_energy_burned, source, plan_workout_id,
        shoe_id, shoe_confirmed, effort_score, estimated_effort_score,
        end_heart_rate, heart_rate_after_1min, heart_rate_after_2min, vo2_max,
        created_at.

        - shoe_id: the pair of shoes the athlete has on this workout; look it
          up in get_shoes. Null means no pair was recorded, not barefoot.
        - shoe_confirmed: false means nobody has checked the pair — the run
          still has whatever it got automatically (the default pair, or none).
          See get_shoes for when that is worth asking the athlete about.

        - source: the HealthKit bundle id of the recording app —
          "com.apple.health.<UUID>" means recorded directly on the Apple Watch
          (the UUID is the device, not an app); others name the app, e.g.
          com.hevyapp.hevy (Hevy strength), com.strava.stravaride (Strava),
          com.garmin.connect.mobile (Garmin), com.bowery-digital.bend (Bend
          stretching).
        - effort_score: User-rated post-workout RPE (1–10) from the Apple Watch
          effort prompt. The user's perception of the workout — trust it as the
          primary signal. May be null when the workout predates iOS 18 / watchOS 11
          or the user dismissed the prompt.
        - estimated_effort_score: Apple's algorithmic RPE estimate (1–10) computed
          from heart rate / activity. Useful for cross-referencing against
          effort_score; a large gap (e.g. user 8 vs. estimate 5) can indicate
          non-cardiovascular load (heat, sleep debt, dehydration, illness, life
          stress) that HR-based estimates miss — worth surfacing during weekly
          review when it appears repeatedly. May be null when no estimate exists.

        Treat null as "no signal," not "low effort."

        - end_heart_rate, heart_rate_after_1min, heart_rate_after_2min: heart
          rate (bpm) as the workout ended and one and two minutes later. The
          recovery drop is end_heart_rate minus the later reading. How the
          athlete stopped decides most of it: a hard effort ended abruptly
          gives a large drop, an easy run or a jogged cooldown a small one, so
          compare only like with like (intervals with intervals, races with
          races) and read a trend over several such sessions, never one run.
          A falling drop across comparable hard sessions can point to fatigue;
          resting heart rate and HRV are the stronger signals for that. Null
          when the watch recorded nothing usable after the end, or the workout
          was paused well before it was ended.
        - vo2_max: the VO2 max estimate (mL/kg/min) Apple Health recorded for
          this workout. Only some outdoor runs, walks and hikes produce one,
          and a single reading moves with heat, hills and pacing; the trend
          is what counts. Null means none was recorded for this workout, or
          the athlete does not share body data with the coach. Do not ask
          them to start tracking it.
    """
    try:
        return await client.list_workouts(
            activity_type=activity_type,
            start_after=start_after,
            start_before=start_before,
            limit=limit,
            shoe_id=shoe_id,
        )
    except Exception as e:
        logger.exception(f"Error in get_recent_runs: {e}")
        return {"error": str(e)}


@workouts_router.tool
@text_result
async def get_workout_detail(workout_id: str) -> dict | list:
    """
    Get full details for a single workout by ID.

    Args:
        workout_id: UUID of the workout.

    Returns:
        Workout object with all fields including the nested data object
        (splits, structured activities, events, metadata). The raw per-second
        sample arrays (GPS route, cadence, heart rate — several hundred kB)
        are replaced by data.samplesSummary: per-series count plus avg/min/max,
        and elevation gain/loss for the route. Use get_workout_heartrate for
        the heart rate series and get_workout_splits for splits.

        data.events contains only meaningful events (pause/resume); HealthKit
        segment events are pruned — they duplicate the interval structure that
        activities and splits already encode.

        Includes effort_score (user-rated RPE 1–10 from Apple Watch effort prompt;
        primary signal of perceived effort) and estimated_effort_score (Apple's
        algorithmic RPE estimate 1–10). A large gap between the two can indicate
        non-cardiovascular load (heat, sleep debt, illness, stress) that HR-based
        estimates miss. Treat null as "no signal," not "low effort."

        shoe_id is the pair of shoes on this workout (see get_shoes), or null
        when none was recorded. shoe_confirmed false means that pair was
        assigned automatically and nobody has checked it.

        end_heart_rate, heart_rate_after_1min and heart_rate_after_2min give
        the heart rate recovery after the workout, and vo2_max the estimate
        Health recorded for it; see get_recent_runs for how to read them.
    """
    try:
        return await client.get_workout(workout_id, include_samples=False)
    except Exception as e:
        logger.exception(f"Error in get_workout_detail: {e}")
        return {"error": str(e)}


@workouts_router.tool
@text_result
async def get_workout_context(workout_id: str) -> dict | list:
    """
    Get the server-held plan linkage for a recorded workout: the queued session
    it fulfilled, the training plan behind that session, and any missed-workout
    feedback filed against it.

    Args:
        workout_id: UUID of the workout (same id as get_recent_runs /
                    get_workout_detail return).

    Returns:
        Object with workout_id, plan_workout_id, plan_link_manual, and three
        nullable keys:
        - queue_item: title, description, activity_type, live status (e.g.
          "completed", "skipped"), scheduled_date, plan_id, the workout_data
          composition that was planned, completed_at.
        - plan: id, name, activity_type, status, start_date, end_date.
        - feedback: reason, reason_note, action (move/adjust/skip), new_date,
          scheduled_date, dismissed, created_at. Survives queue-item deletion.

        All three null (with plan_workout_id null) means an unplanned run —
        that's normal, not an error.

        plan_link_manual true means the athlete linked this workout to the
        session by hand afterwards (or unlinked it). They are saying it counts
        for that session, not that they followed it: it may be from another
        day, another activity, or a different kind of run than prescribed.
        The session is completed either way; read the workout itself for what
        was actually done.

    Useful when reviewing a completed workout: compare what was planned
    (queue_item.workout_data) against what happened, and see what the athlete
    said about the session.
    """
    try:
        return await client.get_workout_context(workout_id)
    except Exception as e:
        logger.exception(f"Error in get_workout_context: {e}")
        return {"error": str(e)}


@workouts_router.tool
@text_result
async def get_workout_splits(workout_id: str) -> dict | list:
    """
    Get per-split data for a workout (e.g. per-km or per-mile splits).

    Args:
        workout_id: UUID of the workout.

    Returns:
        List of split objects extracted from the workout's data.splits field.
    """
    try:
        return await client.get_workout_splits(workout_id)
    except Exception as e:
        logger.exception(f"Error in get_workout_splits: {e}")
        return {"error": str(e)}


@workouts_router.tool
@text_result
async def get_workout_heartrate(
    workout_id: str,
    max_samples: int | None = 500,
) -> dict | list:
    """
    Get the heart rate series recorded during a workout.

    Args:
        workout_id: UUID of the workout.
        max_samples: Cap on series length (default 500, max 5000; null for the
            raw series). Longer series are downsampled by averaging over
            evenly-sized time buckets, so shape and peaks survive — raw counts
            grow with workout duration (a 3 h run is ~2000 samples).

    Returns:
        List of {timestamp, value} heart rate samples in workout order.
    """
    try:
        return await client.get_workout_heartrate(workout_id, max_samples=max_samples)
    except Exception as e:
        logger.exception(f"Error in get_workout_heartrate: {e}")
        return {"error": str(e)}


@workouts_router.tool
@text_result
async def get_workout_activities(workout_id: str) -> dict | list:
    """
    Get the interval/segment breakdown of a workout (warmup, work, rest periods).

    This extracts the 'activities' array from a workout, which describes the
    structured program that was followed — one entry per step the watch ran
    (warmup, work, rest, cooldown), each with distance, duration, heart rate,
    and timing.

    Args:
        workout_id: UUID of the workout.

    Returns:
        List of activity segment objects, each with: activityType, startDate,
        endDate, duration, totalDistance, totalEnergyBurned, averageHeartRate,
        and metadata — metadata.WOIntervalStepKeyPath encodes the position in
        the composed structure as "block.iteration.step" (e.g. "1.2.0" = 2nd
        block, 3rd iteration, 1st step; map it to the queue item's blocks to
        know whether a segment was work or recovery), with
        WOIntervalStepSuccessful/HKElevationAscended alongside.
        Returns an empty list if the workout has no structured activities.
    """
    try:
        workout = await client.get_workout(workout_id, include_samples=False)
        if isinstance(workout, dict):
            data = workout.get("data", {})
            if isinstance(data, dict):
                return data.get("activities", [])
        return []
    except Exception as e:
        logger.exception(f"Error in get_workout_activities: {e}")
        return {"error": str(e)}


@workouts_router.tool
@text_result
async def delete_workout(workout_id: str) -> dict | list:
    """Delete a recorded workout by ID.

    This permanently removes a HealthKit workout record from the database.
    The workout can be re-synced from the iPhone if needed.

    Args:
        workout_id: UUID of the workout to delete.

    Returns:
        Confirmation with the deleted workout ID.
    """
    try:
        return await client.delete_workout(workout_id)
    except Exception as e:
        logger.exception(f"Error in delete_workout: {e}")
        return {"error": str(e)}


@workouts_router.tool
@text_result
async def get_training_summary(
    activity_type: str | None = None,
    period: SummaryPeriod = "month",
    start_after: str | None = None,
    start_before: str | None = None,
    limit: int = 52,
) -> dict | list:
    """
    Get aggregated training summary grouped by time period, newest first.

    Args:
        activity_type: Filter by activity type (e.g. "running"). Omit for all types.
        period: Grouping period - one of "week", "month", or "year" (default "month").
        start_after: Only aggregate workouts starting after this datetime (ISO 8601).
        start_before: Only aggregate workouts starting before this datetime (ISO 8601).
        limit: Max rows returned (default 52, max 500). One row per period ×
               activity_type, newest first — without activity_type a period
               spans multiple rows. History past the limit stays reachable by
               paging back with start_before.

    Returns:
        List of summary objects, each with: period, activity_type, count,
        total_distance, total_duration, avg_distance, avg_duration, total_energy_burned.
    """
    try:
        return await client.get_workout_summary(
            activity_type=activity_type,
            period=period,
            start_after=start_after,
            start_before=start_before,
            limit=limit,
        )
    except Exception as e:
        logger.exception(f"Error in get_training_summary: {e}")
        return {"error": str(e)}
