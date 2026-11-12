"""MCP tool serving the coaching playbook.

The playbook is served as a tool (rather than only an MCP prompt or server
instructions) because tools are the one primitive every MCP client supports —
so any LLM client gets the same methodology on demand, and the content can be
updated server-side without any client changing configuration.
"""

import logging
from typing import Literal

from fastmcp import FastMCP

from training_mcp.coaching import load_playbook
from training_mcp.wire import text_result

logger = logging.getLogger(__name__)

coaching_router = FastMCP(name="Coaching Tools")

Goal = Literal[
    "first_5k",
    "5k",
    "10k",
    "half_marathon",
    "marathon",
    "general_fitness",
]
Experience = Literal["beginner", "intermediate", "advanced"]


@coaching_router.tool
@text_result
def get_coaching_playbook(
    goal: Goal | None = None,
    experience: Experience | None = None,
) -> dict:
    """Load the coaching methodology to follow when acting as a running coach.

    ALWAYS call this before creating a training plan, materially revising one,
    or advising on training structure/load. It returns the evidence-based
    playbook this system follows — pace zones from actual data, intensity
    distribution, progression and recovery rules, readiness gating, and how to
    map methodology onto this API's plans/queue/calendar — plus a module
    tailored to the athlete's goal.

    Not needed for simple data questions ("what did I run last week?").

    Args:
        goal: The athlete's training goal. Use "first_5k" for someone who has
            never run or is starting from zero (couch-to-5K style walk/run
            progression); "general_fitness" when there is no target race.
            Omit if the goal isn't known yet — the core playbook still applies,
            and its intake section helps establish the goal.
        experience: The athlete's experience level, judged from their actual
            training history (get_recent_runs / get_training_summary), not
            self-report alone. Omit to get guidance for all levels.

    Returns:
        Object with:
          - playbook: the methodology as markdown (core principles + goal
            module when a goal was given)
          - goal / experience: what the content was tailored to (null = generic)
          - available_goals: valid goal values
          - warning: present if the requested goal was unknown
    """
    try:
        return load_playbook(goal=goal, experience=experience)
    except Exception as e:
        logger.exception(f"Error in get_coaching_playbook: {e}")
        return {"error": str(e)}
