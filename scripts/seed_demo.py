#!/usr/bin/env python3
"""Seed a Loopback instance with a synthetic demo athlete.

Creates athlete "sofia" and fills ~16 weeks of realistic training through the
public API only (no DB access): runs with splits/heart-rate/cadence/GPS routes,
Hevy-style strength sessions, daily health metrics, nutrition logs, a completed
and an active training plan, a strength schedule, queued sessions (past ones
completed, one skipped with feedback), and coaching notes.

Stdlib-only. Designed for the disposable demo stack:

    docker compose -f docker-compose.demo.yml up -d
    python3 scripts/seed_demo.py
    # dashboard at http://localhost:8011  (admin/demo-admin, sofia/sofia-demo)

Reset with: docker compose -f docker-compose.demo.yml down -v

Data is deterministic for a given --seed but anchored to today's date, so a
fresh demo always looks current. The script refuses to run if the athlete
already exists — reset the stack instead of double-seeding.
"""

import argparse
import json
import math
import random
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import date, datetime, timedelta, timezone

NS = uuid.uuid5(uuid.NAMESPACE_URL, "loopback-demo-seed")

# Lisbon riverfront (Alcântara → Belém), the demo athlete's regular route.
WAYPOINTS = [
    (38.70450, -9.17540),
    (38.70180, -9.18240),
    (38.69890, -9.19110),
    (38.69720, -9.19980),
    (38.69510, -9.20820),
    (38.69260, -9.21600),
]


# ── tiny API client ──────────────────────────────────────────────────────────


class Api:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")
        self.token: str | None = None

    def req(self, method: str, path: str, body: dict | None = None, token: str | None = None):
        url = f"{self.base}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        tok = token or self.token
        if tok:
            req.add_header("Authorization", f"Bearer {tok}")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            sys.exit(f"error: {method} {path} -> {e.code}\n{detail}")

    def wait_ready(self, timeout_s: int = 180) -> None:
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                with urllib.request.urlopen(f"{self.base}/api/health", timeout=5) as resp:
                    if resp.status == 200:
                        return
            except OSError:
                pass
            if time.monotonic() > deadline:
                sys.exit(f"error: API at {self.base} not ready after {timeout_s}s")
            time.sleep(2)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def wid(*parts) -> str:
    return str(uuid.uuid5(NS, ":".join(str(p) for p in parts)))


# ── synthetic workout internals ──────────────────────────────────────────────


def _segment_lengths() -> list[float]:
    out = []
    for (la1, lo1), (la2, lo2) in zip(WAYPOINTS, WAYPOINTS[1:]):
        dx = (lo2 - lo1) * math.cos(math.radians(la1)) * 111_320
        dy = (la2 - la1) * 110_540
        out.append(math.hypot(dx, dy))
    return out


SEG_LEN = _segment_lengths()
PATH_LEN = sum(SEG_LEN)


def _point_at(dist_m: float) -> tuple[float, float]:
    """Position along the riverfront path, ping-ponging for longer runs."""
    k = dist_m % (2 * PATH_LEN)
    if k > PATH_LEN:
        k = 2 * PATH_LEN - k
    for seg_len, (a, b) in zip(SEG_LEN, zip(WAYPOINTS, WAYPOINTS[1:])):
        if k <= seg_len:
            f = k / seg_len
            return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
        k -= seg_len
    return WAYPOINTS[-1]


def route_points(dist_m: float, pace: float, start: datetime, rng: random.Random) -> list[dict]:
    step = 20.0
    out = []
    s = 0.0
    while s <= dist_m:
        lat, lon = _point_at(s)
        out.append(
            {
                "latitude": round(lat + rng.uniform(-3e-5, 3e-5), 6),
                "longitude": round(lon + rng.uniform(-3e-5, 3e-5), 6),
                "altitude": round(6 + 4 * math.sin(s / 500) + rng.uniform(-1, 1), 1),
                "speed": round(1000 / pace + rng.uniform(-0.15, 0.15), 2),
                "timestamp": iso(start + timedelta(seconds=s / 1000 * pace)),
            }
        )
        s += step
    return out


def _hr_target(kind: str, t: float, total: float) -> float:
    warm = min(1.0, t / 360)
    if kind == "intervals":
        if t < 900:
            return 108 + warm * 18
        if t > total - 600:
            return 132
        rep_t = (t - 900) % 270  # 180s work + 90s float
        return 169 if rep_t < 180 else 141
    if kind == "tempo":
        if t < 900:
            return 108 + warm * 22
        if t > total - 600:
            return 135
        return 162
    base = 144 if kind == "long" else 141
    drift = 6 * max(0.0, t / total - 0.5)
    return 108 + warm * (base - 108) + drift


def hr_samples(kind: str, total_s: float, start: datetime, rng: random.Random) -> list[dict]:
    out = []
    t = 0.0
    while t <= total_s:
        val = _hr_target(kind, t, total_s) + rng.uniform(-3, 3)
        out.append({"value": round(val), "timestamp": iso(start + timedelta(seconds=t))})
        t += 30
    return out


def cadence_samples(total_s: float, start: datetime, rng: random.Random, base: float) -> list[dict]:
    out = []
    t = 0.0
    while t <= total_s:
        out.append({"value": round(base + rng.uniform(-3, 3)), "timestamp": iso(start + timedelta(seconds=t))})
        t += 60
    return out


SPLIT_HR = {"easy": 143, "long": 146, "tempo": 158, "intervals": 156}


def make_run(
    day: date,
    start_hm: tuple[int, int],
    kind: str,
    dist_km: float,
    pace: float,
    rng: random.Random,
    plan_workout_id: str | None = None,
) -> dict:
    start = datetime(day.year, day.month, day.day, *start_hm, rng.randrange(60), tzinfo=timezone.utc)
    dist_m = dist_km * 1000
    splits, elapsed, covered = [], 0.0, 0.0
    i = 0
    while covered < dist_m - 1:
        seg = min(1000.0, dist_m - covered)
        p = pace + rng.uniform(-10, 10) + (12 if kind == "intervals" and i == 0 else 0)
        dur = seg * p / 1000
        splits.append(
            {
                "index": i,
                "distance": round(seg, 1),
                "duration": round(dur, 1),
                "pace": round(p, 1),
                "startDate": iso(start + timedelta(seconds=elapsed)),
                "endDate": iso(start + timedelta(seconds=elapsed + dur)),
                "averageHeartRate": round(SPLIT_HR[kind] + rng.uniform(-5, 6) + i * 0.6),
                "averageCadence": round((172 if kind in ("tempo", "intervals") else 166) + rng.uniform(-2, 2)),
                "elevationGain": round(rng.uniform(2, 12), 1),
                "elevationLoss": round(rng.uniform(2, 12), 1),
            }
        )
        covered += seg
        elapsed += dur
        i += 1
    total_s = elapsed + rng.uniform(5, 25)
    est = {"easy": 3.5, "long": 5.5, "tempo": 7.0, "intervals": 8.0}[kind] + rng.uniform(-0.5, 0.5)
    payload = {
        "id": wid("run", day.isoformat(), kind),
        "activityType": "running",
        "startDate": iso(start),
        "endDate": iso(start + timedelta(seconds=total_s)),
        "duration": round(total_s, 1),
        "totalDistance": round(dist_m, 1),
        "totalEnergyBurned": round(dist_km * rng.uniform(58, 66), 1),
        "source": "com.apple.health",
        "estimatedEffortScore": round(est, 1),
        "splits": splits,
        "heartRate": hr_samples(kind, total_s, start, rng),
        "cadence": cadence_samples(total_s, start, rng, 172 if kind in ("tempo", "intervals") else 166),
        "route": route_points(dist_m, pace, start, rng),
    }
    if plan_workout_id:
        payload["planWorkoutId"] = plan_workout_id
    if kind in ("tempo", "intervals") and rng.random() < 0.5:
        payload["effortScore"] = round(min(10, max(1, est + rng.choice([-1, 0, 0, 1]))), 1)
    return payload


def make_simple(day: date, start_hm: tuple[int, int], activity: str, minutes: float, source: str,
                rng: random.Random, dist_km: float | None = None, kcal: float | None = None,
                with_hr: bool = False, hr_base: float = 118) -> dict:
    start = datetime(day.year, day.month, day.day, *start_hm, rng.randrange(60), tzinfo=timezone.utc)
    total_s = minutes * 60 + rng.uniform(-120, 120)
    payload = {
        "id": wid(activity, day.isoformat(), start_hm[0]),
        "activityType": activity,
        "startDate": iso(start),
        "endDate": iso(start + timedelta(seconds=total_s)),
        "duration": round(total_s, 1),
        "source": source,
    }
    if dist_km is not None:
        payload["totalDistance"] = round(dist_km * 1000, 1)
    if kcal is not None:
        payload["totalEnergyBurned"] = round(kcal, 1)
    if with_hr:
        payload["heartRate"] = [
            {"value": round(hr_base + rng.uniform(-10, 14)), "timestamp": iso(start + timedelta(seconds=t))}
            for t in range(0, int(total_s), 60)
        ]
    return payload


# ── compositions (queued sessions) ───────────────────────────────────────────


def _step(purpose: str, goal_type: str, unit: str, value: float) -> dict:
    return {"purpose": purpose, "goal": {"type": goal_type, "unit": unit, "value": value}}


def composition(kind: str, dist_km: float, sched: datetime, reps: int = 6) -> tuple[str, str, dict]:
    km = f"{dist_km:g}"
    if kind == "intervals":
        title = f"{reps} × 3:00 @ 10K effort"
        desc = "Float the recoveries — effort, not pace, on the reps."
        blocks = [{"steps": [_step("work", "time", "seconds", 180), _step("rest", "time", "seconds", 90)], "iterations": reps}]
        warmup, cooldown = _step("warmup", "time", "seconds", 900), _step("cooldown", "time", "seconds", 600)
    elif kind == "tempo":
        title = f"Tempo {km}k @ threshold"
        desc = "Comfortably hard — you should be able to say short sentences."
        blocks = [{"steps": [_step("work", "distance", "meters", dist_km * 1000)], "iterations": 1}]
        warmup, cooldown = _step("warmup", "time", "seconds", 900), _step("cooldown", "time", "seconds", 600)
    elif kind == "long":
        title = f"Long run {km}k"
        desc = "All conversational. Fuel after 45 minutes."
        blocks = [{"steps": [_step("work", "distance", "meters", dist_km * 1000)], "iterations": 1}]
        warmup = cooldown = None
    else:
        title = f"Easy run {km}k"
        desc = "Recovery pace, heart rate in zone 2."
        blocks = [{"steps": [_step("work", "distance", "meters", dist_km * 1000)], "iterations": 1}]
        warmup, cooldown = _step("warmup", "time", "seconds", 600), _step("cooldown", "time", "seconds", 300)
    comp = {
        "displayName": title,
        "activityType": "running",
        "scheduledDate": iso(sched),
        "location": "outdoor",
        "blocks": blocks,
    }
    if warmup:
        comp["warmup"] = warmup
    if cooldown:
        comp["cooldown"] = cooldown
    return title, desc, comp


# ── health metrics ───────────────────────────────────────────────────────────


def health_days(first: date, today: date, rng: random.Random) -> list[dict]:
    n = (today - first).days + 1
    out = []
    for i in range(n):
        d = first + timedelta(days=i)
        f = i / max(1, n - 1)  # 0 → 1 across the window (fitness improving)
        sleep = rng.uniform(6.3, 8.2) * 3600
        deep, rem, awake = sleep * rng.uniform(0.16, 0.22), sleep * rng.uniform(0.20, 0.27), sleep * rng.uniform(0.03, 0.07)
        entry = {
            "date": d.isoformat(),
            "sleepDuration": round(sleep),
            "sleepStages": {
                "deep": round(deep),
                "rem": round(rem),
                "awake": round(awake),
                "core": round(sleep - deep - rem - awake),
            },
            "restingHeartRate": round(57 - 5 * f + rng.uniform(-1.5, 1.5)),
            "hrvSdnn": round(46 + 14 * f + rng.uniform(-7, 7), 1),
            "weight": round(64.0 - 1.0 * f + rng.uniform(-0.35, 0.35), 1),
            "steps": round(rng.uniform(9000, 15000) if d.weekday() >= 5 else rng.uniform(6000, 11000)),
            "activeEnergyBurned": round(rng.uniform(320, 900), 1),
            "respiratoryRate": round(rng.uniform(13.4, 15.4), 1),
            "spo2": round(rng.uniform(0.955, 0.99), 3),
        }
        if i % 3 == 0:
            entry["vo2Max"] = round(44.0 + 2.6 * f + rng.uniform(-0.2, 0.2), 1)
        out.append(entry)
    return out


# ── nutrition ────────────────────────────────────────────────────────────────


def nutrition_days(metrics: list[dict], rng: random.Random) -> list[dict]:
    """Dietary totals keyed to the same days (and weights) as the metrics above.

    Deliberately imperfect, because real food logging is: about a fifth of days
    aren't logged at all, one week is missed entirely, and the most recent day
    is still in progress (`partial`). A demo where every day is logged would
    hide exactly the coverage signals the dashboard and the coach have to reason
    about.
    """
    out: list[dict] = []
    last_index = len(metrics) - 1
    # One entirely unlogged week, ~7 weeks back — a visible gap in adherence.
    gap = range(max(0, last_index - 55), max(0, last_index - 48))

    for i, m in enumerate(metrics):
        if i in gap or (i != last_index and rng.random() < 0.18):
            continue

        d = date.fromisoformat(m["date"])
        weight = m.get("weight") or 64.0
        # Intake tracks the training week: bigger on the long run, smaller on
        # the rest day.
        kind = RUN_DAYS.get(d.weekday())
        bump = {"long": 520, "quality": 210, "easy": 60}.get(kind or "", 0)
        if d.weekday() == 6:  # Sunday: rest
            bump = -180
        energy = 2320 + bump + rng.uniform(-190, 190)

        protein = weight * rng.uniform(1.62, 1.98)
        carb_share = rng.uniform(0.46, 0.56) + (0.04 if kind == "long" else 0)
        carbs = energy * carb_share / 4
        fat = max((energy - carbs * 4 - protein * 4) / 9, 35)

        entry = {
            "date": m["date"],
            "energy_kcal": round(energy),
            "carbs_g": round(carbs, 1),
            "protein_g": round(protein, 1),
            "fat_g": round(fat, 1),
            "saturated_fat_g": round(fat * rng.uniform(0.24, 0.36), 1),
            "fiber_g": round(rng.uniform(22, 38), 1),
            "sugar_g": round(rng.uniform(42, 95), 1),
            "sodium_mg": round(rng.uniform(1900, 3400)),
            "potassium_mg": round(rng.uniform(2300, 3700)),
            "cholesterol_mg": round(rng.uniform(150, 380)),
            "water_ml": round(rng.uniform(1900, 3300)),
            "caffeine_mg": round(rng.uniform(60, 220)),
            "micros": {
                "iron_mg": round(rng.uniform(9, 19), 1),
                "calcium_mg": round(rng.uniform(700, 1400)),
                "magnesium_mg": round(rng.uniform(240, 460)),
                "vitamin_c_mg": round(rng.uniform(45, 180)),
            },
            "entry_count": rng.randint(3, 7),
            "sources": ["MyFitnessPal"],
        }
        if i == last_index:
            # Today, mid-afternoon: roughly two thirds logged so far.
            for key in ("energy_kcal", "carbs_g", "protein_g", "fat_g", "saturated_fat_g",
                        "fiber_g", "sugar_g", "sodium_mg", "potassium_mg", "cholesterol_mg",
                        "water_ml", "caffeine_mg"):
                entry[key] = round(entry[key] * 0.62, 1)
            entry["micros"] = {k: round(v * 0.62, 1) for k, v in entry["micros"].items()}
            entry["entry_count"] = 3
            entry["partial"] = True
        out.append(entry)
    return out


# ── seeding ──────────────────────────────────────────────────────────────────


RUN_DAYS = {0: "easy", 2: "quality", 5: "long"}  # Mon / Wed / Sat
STRENGTH_DAYS = (1, 4)  # Tue / Fri


def week_plan(week_km: float, quality_kind: str) -> dict[int, tuple[str, float]]:
    """Distribute a week's km across the three run days."""
    return {
        0: ("easy", round(week_km * 0.28, 1)),
        2: (quality_kind, round(week_km * 0.32, 1)),
        5: ("long", round(week_km * 0.40, 1)),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Seed a Loopback demo instance with a synthetic athlete.")
    ap.add_argument("--url", default="http://localhost:8011", help="Base URL of the demo API")
    ap.add_argument("--admin-username", default="admin")
    ap.add_argument("--admin-password", default="demo-admin")
    ap.add_argument("--athlete-username", default="sofia")
    ap.add_argument("--athlete-password", default="sofia-demo")
    ap.add_argument("--seed", type=int, default=20260720)
    ap.add_argument(
        "--skip-workouts",
        action="store_true",
        help="Seed everything except recorded workout rows (plans, queue + completions, "
        "feedback, health metrics, notes). For the combined simulator demo: the iOS app's "
        "DEBUG seeder writes the same story into HealthKit and uploads it, so workout ids "
        "match end-to-end.",
    )
    args = ap.parse_args()

    rng = random.Random(args.seed)
    api = Api(args.url)

    print(f"waiting for {args.url} ...")
    api.wait_ready()

    admin = api.req("POST", "/api/auth/login", {"username": args.admin_username, "password": args.admin_password, "deviceName": "seed script"})
    users = api.req("GET", "/api/admin/users", token=admin["token"])
    if any(u["username"] == args.athlete_username for u in users):
        sys.exit(
            f"error: user '{args.athlete_username}' already exists — this instance is seeded.\n"
            "Reset first: docker compose -f docker-compose.demo.yml down -v && docker compose -f docker-compose.demo.yml up -d"
        )
    api.req(
        "POST", "/api/admin/users",
        {"username": args.athlete_username, "password": args.athlete_password, "displayName": "Sofia", "role": "user"},
        token=admin["token"],
    )
    athlete = api.req("POST", "/api/auth/login", {"username": args.athlete_username, "password": args.athlete_password, "deviceName": "Sofia's iPhone"})
    api.token = athlete["token"]
    print(f"created athlete '{args.athlete_username}'")

    today = date.today()
    monday0 = today - timedelta(days=today.weekday())
    plan_start = monday0 - timedelta(weeks=4)
    plan_end = plan_start + timedelta(weeks=8) - timedelta(days=1)
    history_start = plan_start - timedelta(weeks=12)

    # Health metrics (one bulk call)
    metrics = health_days(history_start, today, rng)
    api.req("POST", "/api/health/metrics", {"metrics": metrics})
    print(f"health metrics: {len(metrics)} days")

    nutrition = nutrition_days(metrics, rng)
    api.req("POST", "/api/nutrition", {"days": nutrition})
    print(f"nutrition: {len(nutrition)} of {len(metrics)} days logged (1 partial, 1 week missed)")

    # Fitness improves across the window: pace factor 1.04 → 0.97
    total_days = (today - history_start).days

    def pace_of(kind: str, day: date) -> float:
        base = {"easy": 385, "long": 395, "tempo": 330, "intervals": 318}[kind]
        f = 1.04 - 0.07 * ((day - history_start).days / total_days)
        return base * f

    # ── plans ──
    prev_plan = api.req("POST", "/api/plans", {
        "name": "Spring base block",
        "activityType": "running",
        "status": "completed",
        "startDate": (plan_start - timedelta(weeks=9)).isoformat(),
        "endDate": (plan_start - timedelta(weeks=3, days=1)).isoformat(),
        "description": "Six weeks of aerobic base: mostly easy volume, one light quality session a week.",
        "metadata": {
            "goals": [{"type": "weekly_volume", "target": 26, "unit": "km", "by_week": 6}],
            "phases": [
                {"name": "Base", "weeks": "1-4", "focus": "easy aerobic volume"},
                {"name": "Consolidate", "weeks": "5-6", "focus": "hold volume, add strides"},
            ],
            "completion": {
                "completed_on": (plan_start - timedelta(weeks=3)).isoformat(),
                "rating": 4,
                "feedback": "Consistency was the win — 17 of 18 runs done. Ready for a 10K block.",
            },
        },
    })

    strength_plan = api.req("POST", "/api/plans", {
        "name": "Strength × run support",
        "activityType": "traditionalStrength",
        "status": "active",
        "startDate": (monday0 - timedelta(weeks=8)).isoformat(),
        "endDate": (monday0 + timedelta(weeks=4) - timedelta(days=1)).isoformat(),
        "description": "Two Hevy sessions a week supporting the run block: lower/core and upper/hinge.",
        "metadata": {"goals": [{"type": "habit", "detail": "2 strength sessions per week through the 10K block"}]},
    })
    api.req("PUT", f"/api/plans/{strength_plan['id']}/schedule", {
        "startDate": (monday0 - timedelta(weeks=8)).isoformat(),
        "weeks": 12,
        "days": {
            "tue": {"title": "Lower body + core (Routine A)", "routineId": "demo-hevy-routine-a"},
            "fri": {"title": "Upper body + hinge (Routine B)", "routineId": "demo-hevy-routine-b"},
        },
        "time": "17:30",
        "timezone": "Europe/Lisbon",
    })

    # Created last on purpose: plan-note context resolves to the most recently
    # created active plan, and the run plan is the demo's coaching centrepiece.
    plan = api.req("POST", "/api/plans", {
        "name": "Road to the autumn 10K",
        "activityType": "running",
        "status": "active",
        "startDate": plan_start.isoformat(),
        "endDate": plan_end.isoformat(),
        "description": "Eight-week 10K build: three runs a week (easy / quality / long), down week 4, taper week 8. Goal: sub-55 on race day.",
        "metadata": {
            "goals": [
                {"type": "race", "distance": "10k", "target_time": "0:55:00", "race_date": plan_end.isoformat()},
                {"type": "weekly_volume", "target": 31, "unit": "km", "by_week": 6},
            ],
            "guardrails": {"max_sessions_per_week": 5, "max_weekly_km": 34},
            "phases": [
                {"name": "Build", "weeks": "1-3", "focus": "volume + 10K-effort intervals"},
                {"name": "Absorb", "weeks": "4", "focus": "down week"},
                {"name": "Peak", "weeks": "5-7", "focus": "race-specific tempo"},
                {"name": "Taper", "weeks": "8", "focus": "freshness"},
            ],
            "athlete_context": "Second structured block after a spring of base building. Morning runner, Lisbon riverfront.",
        },
    })
    plan_id = plan["id"]
    print(f"plans: {prev_plan['name']!r} (completed), {plan['name']!r} (active), {strength_plan['name']!r} (+schedule)")

    # ── 12 weeks of pre-plan history (unplanned runs) ──
    n_workouts = 0
    history_km = [20, 21, 23, 24, 25, 21, 26, 27, 28, 24, 27, 28]  # gentle ramp, down weeks 6 + 10
    if not args.skip_workouts:
        for w, km in enumerate(history_km):
            week_monday = history_start + timedelta(weeks=w)
            quality = "tempo" if w % 2 else "easy"
            for dow, (kind, dist) in week_plan(km, quality).items():
                day = week_monday + timedelta(days=dow)
                if day >= plan_start or rng.random() < 0.07:  # the odd missed run
                    continue
                api.req("POST", "/api/workouts", make_run(day, (6, 45), kind, dist, pace_of(kind, day), rng))
                n_workouts += 1

    # ── active plan: queue items + completed workouts, horizon = end of next week ──
    plan_km = [24, 27, 30, 22, 29, 31, 26, 18]
    horizon = monday0 + timedelta(weeks=2)
    skip_day = plan_start + timedelta(weeks=2, days=2)  # week-3 Wednesday, ~2.5 weeks ago
    n_queue = n_done = 0
    for w, km in enumerate(plan_km):
        week_monday = plan_start + timedelta(weeks=w)
        quality = "intervals" if w % 2 == 0 else "tempo"
        for dow, (kind, dist) in week_plan(km, quality).items():
            day = week_monday + timedelta(days=dow)
            if day >= horizon:
                continue
            sched = datetime(day.year, day.month, day.day, 6, 30, tzinfo=timezone.utc)
            if kind == "intervals":
                title, desc, comp = composition(kind, dist, sched, reps=5 + (w >= 4))
            elif kind == "tempo":
                title, desc, comp = composition(kind, round(dist * 0.6, 1), sched)
            else:
                title, desc, comp = composition(kind, dist, sched)
            item = api.req("POST", "/api/queue", {
                "activityType": "running", "title": title, "description": desc,
                "workoutData": comp, "planId": plan_id,
            })
            n_queue += 1
            if day == skip_day:
                api.req("POST", "/api/workouts/feedback", {
                    "id": wid("feedback", day.isoformat()),
                    "workoutId": item["id"],
                    "workoutName": title,
                    "scheduledDate": iso(sched),
                    "detectedAt": iso(sched + timedelta(hours=26)),
                    "acknowledgedAt": iso(sched + timedelta(hours=28)),
                    "reason": "busy",
                    "reasonNote": "Product launch week — no mornings left.",
                    "action": "skip",
                    "dismissed": False,
                })
                continue
            if day <= today:
                api.req("PATCH", f"/api/queue/{item['id']}/status", {"status": "completed"})
                n_done += 1
                if not args.skip_workouts:
                    api.req("POST", "/api/workouts", make_run(day, (6, 40), kind, dist, pace_of(kind, day), rng, plan_workout_id=item["id"]))
                    n_workouts += 1
    print(f"queue: {n_queue} sessions ({n_done} completed, 1 skipped with feedback)")

    # ── strength (Hevy), flexibility (Bend), walks, one ride ──
    for w in range(8 if not args.skip_workouts else 0):
        week_monday = monday0 - timedelta(weeks=8) + timedelta(weeks=w)
        for dow in STRENGTH_DAYS:
            day = week_monday + timedelta(days=dow)
            if day > today or rng.random() < 0.12:
                continue
            api.req("POST", "/api/workouts", make_simple(
                day, (17, 30), "traditionalStrength", rng.uniform(42, 62), "com.hevyapp.hevy",
                rng, kcal=rng.uniform(240, 380), with_hr=True, hr_base=112))
            n_workouts += 1
    for w in range(10 if not args.skip_workouts else 0):
        week_monday = monday0 - timedelta(weeks=10) + timedelta(weeks=w)
        for dow, hm in ((3, (7, 15)), (6, (9, 0))):
            day = week_monday + timedelta(days=dow)
            if day > today or rng.random() < 0.4:
                continue
            api.req("POST", "/api/workouts", make_simple(
                day, hm, "flexibility", rng.uniform(12, 19), "com.bowery-digital.bend", rng, kcal=rng.uniform(35, 70)))
            n_workouts += 1
        sunday = week_monday + timedelta(days=6)
        if sunday <= today and rng.random() < 0.55:
            api.req("POST", "/api/workouts", make_simple(
                sunday, (15, 0), "walking", rng.uniform(45, 85), "com.apple.health",
                rng, dist_km=rng.uniform(3.2, 6.5), kcal=rng.uniform(140, 260)))
            n_workouts += 1
    if not args.skip_workouts:
        ride_day = monday0 - timedelta(weeks=3) + timedelta(days=6)
        api.req("POST", "/api/workouts", make_simple(
            ride_day, (10, 0), "cycling", 92, "com.strava", rng,
            dist_km=28.4, kcal=610, with_hr=True, hr_base=132))
        n_workouts += 1
        print(f"workouts: {n_workouts} total")
    else:
        print("workouts: skipped — the app's HealthKit seed will upload them")

    # ── coaching notes ──
    notes = [
        ("preference", "Prefers morning runs, out the door by 6:45", None, 2, None),
        ("constraint", "History of right-calf tightness — ramp long-run distance gently", "Flared up last spring above 14k long runs. Keep long-run increments ≤1km and watch cadence.", 3, plan_id),
        ("decision", "10K goal race locked in for the end of the block — build to 31 km/wk, taper week 8", None, 3, plan_id),
        ("life_context", "Product launch at work mid-block — expect one lighter week around it", None, 2, None),
        ("observation", "Down week landed well: HRV rebounded and paces felt easier the week after", None, 1, plan_id),
    ]
    for kind, summary, body, importance, pid in notes:
        payload = {"kind": kind, "summary": summary, "importance": importance, "conversationId": "demo-seed"}
        if body:
            payload["body"] = body
        if pid:
            payload["planId"] = pid
        api.req("POST", "/api/plan-notes", payload)
    print(f"plan notes: {len(notes)}")

    minted = api.req("POST", "/api/auth/tokens", {"name": "Demo API token (MCP)"})

    print(
        f"\nDemo instance seeded.\n"
        f"  Dashboard:  {args.url}\n"
        f"  Admin:      {args.admin_username} / {args.admin_password}\n"
        f"  Athlete:    {args.athlete_username} / {args.athlete_password}\n"
        f"  Athlete API token (for MCP or API clients — shown once):\n"
        f"    {minted['token']}\n"
        f"\nReset: docker compose -f docker-compose.demo.yml down -v"
    )


if __name__ == "__main__":
    main()
