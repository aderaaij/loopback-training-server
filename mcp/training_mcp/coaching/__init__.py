"""Coaching playbook content and loader.

The playbook is the coaching methodology the LLM follows when acting as a
running coach. Content lives in markdown files next to this module:

  core.md            — universal principles, always included
  goals/<goal>.md    — one module per training goal, appended when requested

Goal files may contain top-level ``## Beginner`` / ``## Intermediate`` /
``## Advanced`` sections; when an experience level is given, only the matching
section is kept (sections that aren't experience headers are always kept).

Content is plain markdown so it can be edited/reviewed without touching code.
"""

from pathlib import Path

_DIR = Path(__file__).parent
_GOALS_DIR = _DIR / "goals"

EXPERIENCE_LEVELS = ("beginner", "intermediate", "advanced")


def available_goals() -> list[str]:
    """Goal module names, derived from the files on disk."""
    return sorted(p.stem for p in _GOALS_DIR.glob("*.md"))


def _slice_experience(markdown: str, experience: str) -> str:
    """Keep non-experience sections plus the one matching experience section.

    Splits on top-level ``## `` headers. A section whose header is exactly an
    experience level (case-insensitive) is kept only if it matches.
    """
    other_levels = {lvl for lvl in EXPERIENCE_LEVELS if lvl != experience}
    parts = markdown.split("\n## ")
    kept = [parts[0]]
    for part in parts[1:]:
        header = part.split("\n", 1)[0].strip().lower()
        if header in other_levels:
            continue
        kept.append(part)
    return "\n## ".join(kept)


def load_playbook(goal: str | None = None, experience: str | None = None) -> dict:
    """Assemble the playbook: core principles + optional goal module.

    Returns a dict (the MCP tool's payload) rather than bare markdown so the
    response can carry metadata alongside the text.
    """
    sections = [(_DIR / "core.md").read_text()]
    resolved_goal = None

    if goal:
        goal_file = _GOALS_DIR / f"{goal}.md"
        if goal_file.is_file():
            text = goal_file.read_text()
            if experience in EXPERIENCE_LEVELS:
                text = _slice_experience(text, experience)
            sections.append(text)
            resolved_goal = goal

    result: dict = {
        "playbook": "\n\n---\n\n".join(sections),
        "goal": resolved_goal,
        "experience": experience if experience in EXPERIENCE_LEVELS else None,
        "available_goals": available_goals(),
    }
    if goal and not resolved_goal:
        result["warning"] = (
            f"Unknown goal '{goal}' — returned the core playbook only. "
            f"Valid goals: {', '.join(available_goals())}."
        )
    return result
