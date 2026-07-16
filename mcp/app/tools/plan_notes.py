"""MCP tools for plan continuity notes.

These tools let the LLM persist short-form notes about the user's training
plan across conversations. The goal is continuity: any future conversation
can fetch the latest decisions, preferences, and life context with a single
call to ``get_plan_context`` — making each new conversation feel like a
continuation rather than a cold start.

The write tool (``append_plan_note``) is intentionally low-friction: short
notes are cheap, and missing a note is more costly than saving one too many.
"""

import logging
from typing import Any

from fastmcp import FastMCP

from app.schemas import NoteKind
from app.services.api_client import client

logger = logging.getLogger(__name__)

plan_notes_router = FastMCP(name="Plan Notes Tools")


@plan_notes_router.tool
async def get_plan_context(
    plan_id: str | None = None,
    since_days: int = 60,
    limit: int = 40,
) -> dict | list:
    """Load continuity context for the active training plan.

    ALWAYS call this FIRST in any training-related conversation, before
    answering the user. It returns the active plan plus recent notes
    (decisions, preferences, constraints, life context, blockers,
    observations) ranked by importance and recency. This is how you maintain
    continuity across conversations.

    The response includes a `continuity_hint` string — read it. It tells you
    whether continuity is fresh or stale and may instruct you to write notes
    aggressively this conversation.

    Args:
        plan_id: UUID of a specific plan. Omit to use the active plan.
        since_days: Only return notes created within this window (default 60).
        limit: Maximum number of notes to return (default 40, max 200).

    Returns:
        Object with:
          - plan: the resolved plan (or null if none active)
          - notes: list of PlanNote objects (id, kind, summary, body,
            importance, conversation_id, expires_at, created_at), ordered
            by importance desc then created_at desc
          - last_note_age_days: age of the most recent note (or null)
          - continuity_hint: a directive for how aggressively to save notes
            this conversation
    """
    try:
        return await client.get_plan_context(
            plan_id=plan_id,
            since_days=since_days,
            limit=limit,
        )
    except Exception as e:
        logger.exception(f"Error in get_plan_context: {e}")
        return {"error": str(e)}


@plan_notes_router.tool
async def append_plan_note(
    kind: NoteKind,
    summary: str,
    body: str | None = None,
    importance: int = 2,
    expires_at: str | None = None,
    plan_id: str | None = None,
    conversation_id: str | None = None,
) -> dict | list:
    """Save a continuity note about the user's training.

    Call this WITHOUT BEING ASKED whenever ANY of the following happens
    during a conversation:

      • User states a preference. Trigger phrases: "I prefer", "I like",
        "I hate", "from now on", "going forward", "always", "never".
      • User makes a plan decision. Trigger phrases: "let's drop", "let's
        switch", "let's add", "I've decided", "I'm going to", "this week
        I'll", "starting Monday".
      • User reveals life context that affects training. Examples:
        travel, illness, injury, sleep debt, work stress, life events,
        weather constraints, schedule shifts.
      • User commits to a change in approach.
      • A non-obvious insight emerges that future-you would want to know
        but couldn't infer from workout data alone.

    DO save short, partial notes — they are cheap. DO NOT save: chitchat,
    things derivable from workout/health-metrics data, code-level details,
    or one-off acknowledgments.

    Tip: if a note is temporal (e.g. "traveling Mar 1–5"), set
    `expires_at` so it auto-fades from future context.

    Args:
        kind: One of:
          - "decision"     — the user committed to a plan-level change
          - "preference"   — a stable preference about how training works
          - "constraint"   — a hard limit (schedule, equipment, injury)
          - "life_context" — temporary life situation affecting training
          - "observation"  — non-obvious insight worth remembering
          - "blocker"      — something preventing planned training
        summary: One-line summary, ≤280 chars. Lead with the fact, not
            "the user said". Example: "Prefers morning runs, never evenings."
        body: Optional longer body — the *why*, edge cases, exceptions.
            Future-you reads this when the summary alone is ambiguous.
        importance: 1=low, 2=med (default), 3=high. Use 3 sparingly for
            hard constraints and committed decisions.
        expires_at: Optional ISO 8601 datetime. After this, the note is
            excluded from `get_plan_context` results. Use for temporal
            life_context notes (travel, short-term illness, etc.).
        plan_id: Optional plan UUID. Omit for global notes that apply
            across all plans (e.g. stable preferences).
        conversation_id: Optional opaque string to group all notes from
            one conversation. Use a stable id throughout the conversation
            so future-you can replay what was discussed together.

    Returns:
        The created PlanNote object.
    """
    try:
        body_payload: dict[str, Any] = {
            "kind": kind,
            "summary": summary,
            "importance": importance,
        }
        if body is not None:
            body_payload["body"] = body
        if expires_at is not None:
            body_payload["expiresAt"] = expires_at
        if plan_id is not None:
            body_payload["planId"] = plan_id
        if conversation_id is not None:
            body_payload["conversationId"] = conversation_id
        return await client.create_plan_note(body_payload)
    except Exception as e:
        logger.exception(f"Error in append_plan_note: {e}")
        return {"error": str(e)}


@plan_notes_router.tool
async def list_plan_notes(
    plan_id: str | None = None,
    kind: NoteKind | None = None,
    conversation_id: str | None = None,
    since_days: int | None = None,
    include_expired: bool = False,
    limit: int = 50,
) -> dict | list:
    """List plan notes with filters. Use this for targeted retrieval (e.g.
    only "decision" notes, or all notes from a specific conversation_id).

    For the standard conversation-start fetch, use `get_plan_context`
    instead — it returns plan + notes + a continuity hint in one call.

    Args:
        plan_id: Filter by plan UUID.
        kind: Filter by kind (decision, preference, constraint,
            life_context, observation, blocker).
        conversation_id: Filter by conversation grouping id.
        since_days: Only notes created within this window.
        include_expired: If true, include notes past their expires_at.
        limit: Max notes to return (default 50, max 200).

    Returns:
        List of PlanNote objects ordered by importance desc, created_at desc.
    """
    try:
        return await client.list_plan_notes(
            plan_id=plan_id,
            kind=kind,
            conversation_id=conversation_id,
            since_days=since_days,
            include_expired=include_expired,
            limit=limit,
        )
    except Exception as e:
        logger.exception(f"Error in list_plan_notes: {e}")
        return {"error": str(e)}


@plan_notes_router.tool
async def update_plan_note(
    note_id: str,
    kind: NoteKind | None = None,
    summary: str | None = None,
    body: str | None = None,
    importance: int | None = None,
    expires_at: str | None = None,
) -> dict | list:
    """Update a plan note. Use when a previous note was wrong, became
    obsolete, or needs a tighter summary. Prefer updating over deleting +
    re-creating so the note's history is preserved.

    Args:
        note_id: UUID of the note.
        kind: New kind, if changing categorization.
        summary: New one-line summary (≤280 chars).
        body: New body text.
        importance: New importance (1–3).
        expires_at: New expiry, or pass to add expiry to a note that
            didn't have one.

    Returns:
        The updated PlanNote.
    """
    try:
        updates: dict[str, Any] = {}
        if kind is not None:
            updates["kind"] = kind
        if summary is not None:
            updates["summary"] = summary
        if body is not None:
            updates["body"] = body
        if importance is not None:
            updates["importance"] = importance
        if expires_at is not None:
            updates["expiresAt"] = expires_at
        return await client.update_plan_note(note_id, updates)
    except Exception as e:
        logger.exception(f"Error in update_plan_note: {e}")
        return {"error": str(e)}


@plan_notes_router.tool
async def delete_plan_note(note_id: str) -> dict | list:
    """Delete a plan note. Use only when the note was incorrect or
    duplicated. Prefer `update_plan_note` (or setting `expires_at` for
    temporal notes) over deletion — deleted notes lose history.

    Args:
        note_id: UUID of the note to delete.

    Returns:
        Confirmation with the deleted note id.
    """
    try:
        return await client.delete_plan_note(note_id)
    except Exception as e:
        logger.exception(f"Error in delete_plan_note: {e}")
        return {"error": str(e)}
