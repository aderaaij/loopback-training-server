"""MCP tools for setbacks: the athlete's illnesses and injuries.

Advertised only to an athlete who shares `recovery` with the coach (see
training_mcp/consent.py), so the guidance lives here on the tools and not in
the server instructions, which every athlete's client reads.
"""

import logging
from datetime import date as date_type
from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from pydantic import Field

from training_mcp.services.api_client import client
from training_mcp.wire import text_result

logger = logging.getLogger(__name__)

setbacks_router = FastMCP(name="Setback Tools")

SetbackKind = Literal["illness", "injury"]
SetbackSeverity = Literal["mild", "moderate", "severe"]
SetbackStatus = Literal["worse", "same", "better", "fine"]


@setbacks_router.tool
@text_result
async def get_setbacks(active_only: bool = False, since: str | None = None) -> dict | list:
    """
    List the athlete's illnesses and injuries, with how they felt day by day.

    get_plan_context already hands you the open ones and the ones that ended
    in the last three weeks, so you rarely need this at the start of a
    conversation. Use it for the history: how often the athlete is set back,
    how long each one lasted, and how past ones compare with the current one.

    READING ONE AGAINST THE DATA. A setback gives you the dates; the effect is
    in the other tools. To see what an illness did, compare the days from
    `startDate` on with the two to four weeks before it: resting heart rate,
    HRV, respiratory rate, sleeping wrist temperature and sleep from
    get_health_metrics, and for the runs
    after it the heart rate at a given easy pace and the heart rate recovery
    from get_recent_runs and get_workout_detail. Raised resting heart rate and
    lowered HRV that have come back to the earlier range for a few days in a
    row, together with the athlete saying they feel fine, is what recovered
    looks like. For an injury the numbers say little: go by the daily status
    and by runs completed without pain. Say what you see and how sure you are;
    this is not a diagnosis.

    Args:
        active_only: Only setbacks that are still going on.
        since: Only setbacks still going on or ended on or after this day
               (YYYY-MM-DD).

    Returns:
        List of setbacks, open ones first, then the most recently started.
        Keys are camelCase:

        - id: pass to update_setback and log_setback_status.
        - kind: "illness" or "injury".
        - severity: "mild", "moderate" or "severe", the athlete's own call.
        - startDate / endDate: first and last day (YYYY-MM-DD, the athlete's
          local days). endDate is null while it is still going on.
        - active: true while there is no end date.
        - days: length in days, both ends counted; for an open one, through
          today.
        - bodyPart: injuries only, free text; may be null.
        - note: the athlete's description; may be null.
        - checkins: one entry per day the athlete (or you) recorded a status,
          oldest first: date, status ("worse", "same", "better", "fine"),
          note. Days without an entry were simply not recorded.
        - recovery: open setbacks only, else null. The server's own read of
          whether it looks over. `status` is "looks_recovered", "not_yet" or
          "insufficient_data"; `summary` says why in a sentence; `metrics`
          lists resting heart rate, HRV, breathing rate and sleeping wrist
          temperature (those the athlete has data for) with the
          athlete's `usual` (median of the four weeks before), the
          `tolerance` around it, the `latest` reading and its `state`
          ("normal", "off", "no_recent_data"). `basis` is "metrics" or
          "status" (the athlete said "fine" two days running, or a fresh
          "worse"/"same" is holding it back). It is a prompt to ask the
          athlete, never grounds to close a setback yourself. Injuries get
          no metrics: the numbers say little about them.
    """
    try:
        return await client.list_setbacks(active=True if active_only else None, since=since)
    except Exception as e:
        logger.exception(f"Error in get_setbacks: {e}")
        return {"error": str(e)}


@setbacks_router.tool
@text_result
async def log_setback(
    kind: SetbackKind,
    start_date: str,
    severity: SetbackSeverity = "moderate",
    end_date: str | None = None,
    body_part: Annotated[str | None, Field(max_length=80)] = None,
    note: Annotated[str | None, Field(max_length=2000)] = None,
) -> dict | list:
    """
    Record that the athlete is, or was, ill or injured.

    Call this WITHOUT BEING ASKED when the athlete tells you they are sick or
    hurt, or that they were on days you had no setback for ("I had the flu
    last weekend", "my calf has been sore since Tuesday's intervals"). This is
    what makes the next conversation start out knowing it. Check the
    `setbacks` in get_plan_context first: if the same one is already open,
    use update_setback or log_setback_status on it. The server refuses a
    second open illness, and a second open injury to the same body part.

    Ordinary training soreness that fades within two days is not a setback.
    Tell the athlete you have logged it, in one short sentence.

    Args:
        kind: "illness" (cold, flu, stomach bug, covid) or "injury".
        start_date: First day affected, YYYY-MM-DD. Ask if it is unclear;
            it is the anchor every before/after comparison uses.
        severity: "mild" (could have trained easy), "moderate" (no training)
            or "severe" (in bed, or cannot walk without pain). Ask rather
            than guess when the athlete's words do not settle it.
        end_date: Last day affected, YYYY-MM-DD. Leave out while it is still
            going on, and while the athlete is "better but not right yet".
        body_part: Injuries only, in the athlete's words ("left calf").
        note: Symptoms and anything that explains it, in a line or two.

    Returns:
        The setback, in the shape get_setbacks lists.
    """
    try:
        body: dict[str, Any] = {"kind": kind, "startDate": start_date, "severity": severity}
        if end_date is not None:
            body["endDate"] = end_date
        if body_part is not None:
            body["bodyPart"] = body_part
        if note is not None:
            body["note"] = note
        return await client.create_setback(body)
    except Exception as e:
        logger.exception(f"Error in log_setback: {e}")
        return {"error": str(e)}


@setbacks_router.tool
@text_result
async def update_setback(
    setback_id: str,
    end_date: str | None = None,
    reopen: bool = False,
    severity: SetbackSeverity | None = None,
    start_date: str | None = None,
    kind: SetbackKind | None = None,
    body_part: Annotated[str | None, Field(max_length=80)] = None,
    note: Annotated[str | None, Field(max_length=2000)] = None,
) -> dict | list:
    """
    Change a setback: close it, reopen it, or correct what was recorded.
    Only what you pass changes.

    CLOSING. Set `end_date` when the athlete says they are recovered. Their
    word decides it, not the numbers: if the metrics look normal but they
    still feel off, it stays open, and if they say they are fine while resting
    heart rate is still raised, close it and say what you see. After closing,
    the plan still needs a gradual build back (coaching playbook, return to
    running).

    Args:
        setback_id: The setback's id, from get_plan_context or get_setbacks.
        end_date: Last day affected, YYYY-MM-DD. Closes the setback.
        reopen: True to clear the end date, when it came back.
        severity: "mild", "moderate" or "severe".
        start_date: Corrected first day, YYYY-MM-DD.
        kind: "illness" or "injury".
        body_part: Injuries only.
        note: Replaces the note. Include what was there if it still holds.

    Returns:
        The setback after the change.
    """
    try:
        if reopen and end_date is not None:
            return {"error": "Pass either end_date or reopen, not both."}
        changes: dict[str, Any] = {}
        if reopen:
            changes["endDate"] = None
        if end_date is not None:
            changes["endDate"] = end_date
        if severity is not None:
            changes["severity"] = severity
        if start_date is not None:
            changes["startDate"] = start_date
        if kind is not None:
            changes["kind"] = kind
        if body_part is not None:
            changes["bodyPart"] = body_part
        if note is not None:
            changes["note"] = note
        if not changes:
            return {"error": "Nothing to change: pass at least one field."}
        return await client.update_setback(setback_id, changes)
    except Exception as e:
        logger.exception(f"Error in update_setback: {e}")
        return {"error": str(e)}


@setbacks_router.tool
@text_result
async def log_setback_status(
    setback_id: str,
    status: SetbackStatus,
    date: str | None = None,
    note: Annotated[str | None, Field(max_length=2000)] = None,
) -> dict | list:
    """
    Record how the athlete felt on one day of a setback.

    While a setback is open, ask how they are today when the conversation
    starts and record the answer here, unless today already has an entry. One
    entry per day; logging the same day again replaces it. These entries are
    the subjective side of the recovery curve, and for an injury they are most
    of it.

    "fine" does not close the setback. When the athlete says "fine", ask
    whether they consider themselves recovered, and close it with
    update_setback if they do.

    Args:
        setback_id: The setback's id.
        status: "worse", "same" or "better" compared with the day before, or
            "fine" when they feel normal again.
        date: The day it describes, YYYY-MM-DD. Defaults to today; pass it
            when the athlete is describing an earlier day.
        note: Their words, shortened ("fever gone, still coughing").

    Returns:
        The setback with its check-ins.
    """
    try:
        day = date or date_type.today().isoformat()
        body: dict[str, Any] = {"status": status}
        if note is not None:
            body["note"] = note
        return await client.put_setback_checkin(setback_id, day, body)
    except Exception as e:
        logger.exception(f"Error in log_setback_status: {e}")
        return {"error": str(e)}
