"""Pure plan-soundness validation.

A deterministic "linter" for the athlete's upcoming schedule: checks queued
workout compositions against recorded workout history. No I/O and no ORM
imports — the caller (validation_service) fetches rows and passes plain data.

The thresholds encode the numeric invariants of the coaching playbook served
by the MCP (mcp/app/coaching/core.md): weekly volume within ~1.3× the 4-week
baseline, a down week every few weeks, long run ≤ ~30% of the week, no
back-to-back hard days, a taper that actually tapers. Warnings never block —
the coach (LLM or human) decides; the validator's job is making sure the
numbers get seen.

Estimation caveats, by design:
- Time-goal steps convert to distance via the step's speed alert, else the
  athlete's observed easy speed, else a conservative default; anything using
  an assumed speed carries ``estimated: true``.
- "Hard" is structural: an interval block (work/rest × 2+) or a steady step
  with a speed alert faster than easy pace. Walk/run beginner sessions
  therefore classify as hard — harmless, since those plans never schedule
  consecutive days.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median

RAMP_WARN_RATIO = 1.3
RAMP_CRITICAL_RATIO = 1.5
MIN_BASELINE_KM = 10.0  # below this, ratios are meaningless — use absolute checks
NO_BASELINE_WARN_KM = 25.0
NO_BASELINE_CRITICAL_KM = 40.0
LONG_RUN_SHARE_WARN = 0.35  # playbook guideline is 30%; warn with margin
LONG_RUN_MIN_WEEK_KM = 25.0  # at low volume a big long-run share is normal
DOWN_WEEK_DROP = 0.85  # a week below 85% of the previous counts as recovery
WEEKS_WITHOUT_DOWN = 4
FREQUENCY_JUMP = 2
TAPER_FINAL_WEEK_SHARE = 0.6
DEFAULT_EASY_SPEED_MS = 2.6  # ~6:25/km — conservative recreational easy pace
HARD_SPEED_FACTOR = 1.05

_SEVERITY_ORDER = {"critical": 0, "warn": 1, "info": 2}


@dataclass(frozen=True)
class HistoryRun:
    date: date
    distance_m: float | None
    duration_s: float | None


@dataclass
class PlannedSession:
    date: date
    title: str
    distance_m: float = 0.0
    duration_s: float = 0.0
    hard: bool = False
    estimated: bool = False
    has_data: bool = True


def estimate_easy_speed(history: list[HistoryRun]) -> float | None:
    """Median speed (m/s) over real runs — a fair easy-pace proxy."""
    speeds = [
        r.distance_m / r.duration_s
        for r in history
        if r.distance_m and r.duration_s and r.duration_s >= 600 and r.distance_m >= 1000
    ]
    return median(speeds) if speeds else None


def _step_speed(step: dict, fallback: float) -> tuple[float, bool]:
    """Speed to convert a time goal to distance: alert band midpoint, else
    the fallback (marked estimated)."""
    alert = step.get("alert") or {}
    if alert.get("type") in ("speed", "pace"):
        lo, hi = alert.get("min"), alert.get("max")
        if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and lo > 0 and hi > 0:
            return (lo + hi) / 2, False
    return fallback, True


def _step_volume(step: dict, easy_speed: float) -> tuple[float, float, bool]:
    """(distance_m, duration_s, estimated) for one composition step."""
    goal = step.get("goal") or {}
    value = goal.get("value")
    if not isinstance(value, (int, float)) or value <= 0:
        return 0.0, 0.0, True  # open/absent goal — unknown volume
    unit = goal.get("unit")
    if goal.get("type") == "distance":
        meters = value * 1000 if unit in ("kilometers", "km") else value
        speed, _ = _step_speed(step, easy_speed)
        return meters, meters / speed, False
    if goal.get("type") == "time":
        seconds = value * 60 if unit in ("minutes", "min") else value
        speed, assumed = _step_speed(step, easy_speed)
        return seconds * speed, seconds, assumed
    return 0.0, 0.0, True


def session_from_composition(
    workout_data: dict | None,
    on_date: date,
    title: str,
    easy_speed: float | None,
) -> PlannedSession:
    """Reduce a workout composition to date/volume/intensity facts."""
    if not workout_data:
        return PlannedSession(date=on_date, title=title, has_data=False, estimated=True)

    speed = easy_speed or DEFAULT_EASY_SPEED_MS
    session = PlannedSession(date=on_date, title=title, estimated=easy_speed is None)

    def add_step(step: dict, iterations: int = 1) -> None:
        m, s, assumed = _step_volume(step, speed)
        session.distance_m += m * iterations
        session.duration_s += s * iterations
        if assumed and (m or s):
            session.estimated = True

    for key in ("warmup", "cooldown"):
        if isinstance(workout_data.get(key), dict):
            add_step(workout_data[key])

    for block in workout_data.get("blocks") or []:
        steps = block.get("steps") or []
        iterations = block.get("iterations") or 1
        purposes = {s.get("purpose") for s in steps}
        # "recovery" is the current schema's term; "rest" appears in older rows
        if iterations >= 2 and "work" in purposes and purposes & {"rest", "recovery"}:
            session.hard = True
        for step in steps:
            add_step(step, iterations)
            if step.get("purpose") not in ("rest", "recovery"):
                alert = step.get("alert") or {}
                if alert.get("type") in ("speed", "pace"):
                    lo = alert.get("min")
                    if isinstance(lo, (int, float)) and lo > speed * HARD_SPEED_FACTOR:
                        session.hard = True

    return session


def extract_race_date(metadata: dict | None) -> date | None:
    """Dig plan.metadata for a race date (LLM-written, so be lenient)."""
    for container in (metadata or {}, (metadata or {}).get("goals") or {}):
        if not isinstance(container, dict):
            continue
        for key in ("race_date", "raceDate"):
            raw = container.get(key)
            if isinstance(raw, str):
                try:
                    return date.fromisoformat(raw[:10])
                except ValueError:
                    pass
    return None


def extract_guardrails(metadata: dict | None) -> dict:
    """Normalize recognized guardrail keys out of plan.metadata.guardrails."""
    raw = (metadata or {}).get("guardrails")
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    for norm, keys in (
        ("max_sessions_per_week", ("max_sessions_per_week", "maxSessionsPerWeek")),
        ("max_weekly_km", ("max_weekly_km", "maxWeeklyKm")),
    ):
        for key in keys:
            value = raw.get(key)
            if isinstance(value, (int, float)) and value > 0:
                out[norm] = value
                break
    return out


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def validate_schedule(
    planned: list[PlannedSession],
    history: list[HistoryRun],
    *,
    today: date,
    race_date: date | None = None,
    guardrails: dict | None = None,
    strength_dates: frozenset[date] | set[date] = frozenset(),
) -> tuple[list[dict], list[dict]]:
    """Run every check. Returns (warnings, week_summaries).

    ``planned`` should be the athlete's upcoming schedule (today onward);
    ``history`` their recorded runs. Weeks are ISO (Monday-keyed).
    """
    warnings: list[dict] = []

    def warn(code: str, severity: str, message: str, week: date | None = None,
             data: dict | None = None, estimated: bool = False) -> None:
        warnings.append({
            "code": code,
            "severity": severity,
            "message": message,
            "week": week.isoformat() if week else None,
            "data": data or {},
            "estimated": estimated,
        })

    # ── weekly aggregation (merged timeline: history + plan) ──
    actual_km: dict[date, float] = defaultdict(float)
    actual_days: dict[date, set[date]] = defaultdict(set)
    planned_km: dict[date, float] = defaultdict(float)
    planned_days: dict[date, set[date]] = defaultdict(set)
    hard_dates: set[date] = set()
    longest: dict[date, float] = defaultdict(float)
    week_estimated: dict[date, bool] = defaultdict(bool)

    for run in history:
        wk = _monday(run.date)
        actual_km[wk] += (run.distance_m or 0) / 1000
        actual_days[wk].add(run.date)

    no_data_sessions = 0
    for s in planned:
        wk = _monday(s.date)
        planned_km[wk] += s.distance_m / 1000
        planned_days[wk].add(s.date)
        longest[wk] = max(longest[wk], s.distance_m / 1000)
        week_estimated[wk] = week_estimated[wk] or s.estimated
        if s.hard:
            hard_dates.add(s.date)
        if not s.has_data:
            no_data_sessions += 1

    if no_data_sessions:
        warn("missing_composition", "info",
             f"{no_data_sessions} scheduled item(s) have no workout composition — "
             "volume checks underestimate those weeks.")

    def total(wk: date) -> float:
        return actual_km.get(wk, 0.0) + planned_km.get(wk, 0.0)

    evaluated = sorted(wk for wk, days in planned_days.items() if days)
    if not evaluated:
        return warnings, []

    has_history = bool(history)
    summaries: list[dict] = []

    # ── per-week checks: ramp rate, long-run share, guardrails, rest days ──
    for wk in evaluated:
        prior_weeks = [wk - timedelta(weeks=i) for i in range(1, 5)]
        prior = [total(w) for w in prior_weeks]
        baseline = sum(prior) / 4 if (has_history or any(prior)) else None
        ratio = round(total(wk) / baseline, 2) if baseline and baseline >= MIN_BASELINE_KM else None
        week_km = total(wk)
        data = {"week_km": round(week_km, 1), "baseline_km": round(baseline, 1) if baseline is not None else None}

        if ratio is not None:
            severity = "critical" if ratio > RAMP_CRITICAL_RATIO else "warn" if ratio > RAMP_WARN_RATIO else None
            # A layoff inside the 4-week window drags the baseline down and
            # inflates every ratio measured against it — the athlete cannot
            # comply without prescribing detraining, and an unfixable
            # `critical` teaches the reader to discount the word. Zero weeks
            # are still counted (dropping them would silently redefine the
            # average as "weeks you happened to run", and let a 2-week layoff
            # resume at full volume with no warning at all), but the severity
            # is capped and the constituent weeks ship with the warning so the
            # number can be checked rather than trusted.
            rest_weeks = [w for w, km in zip(prior_weeks, prior) if km == 0.0]
            if severity == "critical" and rest_weeks:
                severity = "warn"
            if severity:
                note = (
                    f" Baseline spans {len(rest_weeks)} week(s) with no running "
                    f"({', '.join(w.isoformat() for w in rest_weeks)}), which lowers it."
                    if rest_weeks else ""
                )
                warn("ramp_rate", severity,
                     f"Week of {wk.isoformat()}: {week_km:.0f} km vs 4-week baseline "
                     f"{baseline:.0f} km ({ratio:.2f}×). Playbook guideline is ≤1.3×.{note}",
                     week=wk,
                     data={**data, "ratio": ratio,
                           "baseline_weeks": [
                               {"week": w.isoformat(), "km": round(km, 1)}
                               for w, km in zip(prior_weeks, prior)
                           ]},
                     estimated=week_estimated[wk])
        elif week_km > NO_BASELINE_WARN_KM:
            severity = "critical" if week_km > NO_BASELINE_CRITICAL_KM else "warn"
            warn("volume_without_baseline", severity,
                 f"Week of {wk.isoformat()} plans {week_km:.0f} km but the athlete has "
                 f"{'no recorded history' if baseline is None else f'a baseline of only {baseline:.0f} km'} "
                 "to support it.",
                 week=wk, data=data, estimated=week_estimated[wk])

        if week_km >= LONG_RUN_MIN_WEEK_KM and longest[wk] / week_km > LONG_RUN_SHARE_WARN:
            warn("long_run_share", "warn",
                 f"Week of {wk.isoformat()}: longest run {longest[wk]:.0f} km is "
                 f"{longest[wk] / week_km:.0%} of the week's {week_km:.0f} km "
                 "(playbook guideline ≤30%).",
                 week=wk, data={"longest_km": round(longest[wk], 1), **data},
                 estimated=week_estimated[wk])

        rails = guardrails or {}
        run_days = planned_days[wk] | actual_days.get(wk, set())
        if "max_sessions_per_week" in rails and len(run_days) > rails["max_sessions_per_week"]:
            warn("guardrail_breach", "critical",
                 f"Week of {wk.isoformat()} has {len(run_days)} run days; the plan's own "
                 f"guardrail caps it at {rails['max_sessions_per_week']:.0f}.",
                 week=wk, data={"run_days": len(run_days), "cap": rails["max_sessions_per_week"]})
        if "max_weekly_km" in rails and week_km > rails["max_weekly_km"]:
            warn("guardrail_breach", "critical",
                 f"Week of {wk.isoformat()} plans {week_km:.0f} km; the plan's own "
                 f"guardrail caps it at {rails['max_weekly_km']:.0f} km.",
                 week=wk, data={**data, "cap": rails["max_weekly_km"]}, estimated=week_estimated[wk])
        if len(run_days) >= 7:
            warn("no_rest_day", "warn",
                 f"Week of {wk.isoformat()} has running on all 7 days — no rest day.",
                 week=wk, data={"run_days": len(run_days)})

        summaries.append({
            "week_start": wk.isoformat(),
            "planned_km": round(planned_km[wk], 1),
            "actual_km": round(actual_km.get(wk, 0.0), 1),
            "total_km": round(week_km, 1),
            "run_days": len(run_days),
            "hard_days": sum(1 for d in hard_dates if _monday(d) == wk),
            "longest_km": round(longest[wk], 1),
            "baseline_km": round(baseline, 1) if baseline is not None else None,
            "ratio": ratio,
            "estimated": week_estimated[wk],
        })

    # ── missing down week: consecutive planned weeks that never back off ──
    streak_start: date | None = None
    streak = 0
    reported_down = False
    for prev, wk in zip(evaluated, evaluated[1:]):
        contiguous = wk - prev == timedelta(weeks=1)
        recovered = total(wk) < total(prev) * DOWN_WEEK_DROP
        if not contiguous or recovered:
            streak, streak_start = 0, None
            continue
        streak += 1
        streak_start = streak_start or prev
        rising = total(wk) > total(streak_start) * 1.1
        if streak >= WEEKS_WITHOUT_DOWN and rising and not reported_down:
            warn("missing_down_week", "warn",
                 f"Volume climbs from the week of {streak_start.isoformat()} through "
                 f"{wk.isoformat()} with no recovery week (playbook: cut ~30% every "
                 "3rd–4th week).",
                 week=wk, data={"streak_weeks": streak + 1})
            reported_down = True

    # ── hard-day spacing: consecutive calendar days ──
    ordered_hard = sorted(hard_dates)
    cluster: list[date] = []
    for d in ordered_hard:
        if cluster and (d - cluster[-1]).days == 1:
            cluster.append(d)
        else:
            cluster = [d]
        if len(cluster) == 2:
            warn("hard_day_spacing", "warn",
                 f"Hard sessions on consecutive days: {cluster[0].isoformat()} and "
                 f"{cluster[1].isoformat()}.",
                 week=_monday(cluster[0]), data={"dates": [x.isoformat() for x in cluster]})
        elif len(cluster) == 3:
            warnings[-1].update(severity="critical", message=(
                f"Three consecutive hard days starting {cluster[0].isoformat()}."))

    # ── frequency jump vs recent habit ──
    hist_weeks = [len(days) for wk, days in actual_days.items()
                  if today - timedelta(weeks=8) <= wk < _monday(today)]
    if len(hist_weeks) >= 3:
        habitual_max = max(hist_weeks)
        for wk in evaluated:
            if len(planned_days[wk]) > habitual_max + FREQUENCY_JUMP:
                warn("frequency_jump", "warn",
                     f"Week of {wk.isoformat()} plans {len(planned_days[wk])} run days; "
                     f"the athlete's recent max is {habitual_max} days/week.",
                     week=wk, data={"planned_days": len(planned_days[wk]), "recent_max": habitual_max})
                break  # once is enough — later weeks usually inherit the pattern

    # ── taper shape before a declared race ──
    if race_date and len(evaluated) >= 3:
        pre_race = [wk for wk in evaluated if wk < _monday(race_date)]
        if pre_race:
            peak = max(total(wk) for wk in evaluated)
            final = pre_race[-1]
            if _monday(race_date) - final == timedelta(weeks=1) and peak > 0 \
                    and total(final) > peak * TAPER_FINAL_WEEK_SHARE:
                warn("no_taper", "warn",
                     f"Final full week before the race ({final.isoformat()}) holds "
                     f"{total(final):.0f} km — {total(final) / peak:.0%} of peak. Playbook "
                     "taper: cut volume 40–60%, keep intensity.",
                     week=final, data={"final_km": round(total(final), 1), "peak_km": round(peak, 1)})
        for d in ordered_hard:
            if 0 < (race_date - d).days <= 2:
                warn("hard_near_race", "warn",
                     f"Hard session on {d.isoformat()}, {(race_date - d).days} day(s) "
                     "before the race.",
                     week=_monday(d), data={"date": d.isoformat()})

    # ── strength collision: quality run the day after a strength session ──
    for d in ordered_hard:
        if d - timedelta(days=1) in strength_dates:
            warn("strength_collision", "info",
                 f"Hard run on {d.isoformat()} directly after the "
                 f"{(d - timedelta(days=1)).isoformat()} strength session.",
                 week=_monday(d), data={"date": d.isoformat()})

    # ── sanity: doubles and past-dated items ──
    seen: set[date] = set()
    for s in sorted(planned, key=lambda x: x.date):
        if s.date in seen:
            warn("double_day", "info",
                 f"Two scheduled sessions on {s.date.isoformat()}.",
                 week=_monday(s.date), data={"date": s.date.isoformat()})
        seen.add(s.date)
        if s.date < today:
            warn("past_scheduled", "info",
                 f"'{s.title}' is scheduled in the past ({s.date.isoformat()}).",
                 week=_monday(s.date), data={"date": s.date.isoformat()})

    warnings.sort(key=lambda w: (_SEVERITY_ORDER[w["severity"]], w["week"] or ""))
    return warnings, summaries
