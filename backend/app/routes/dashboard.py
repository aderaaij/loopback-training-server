from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from app.config import get_settings
from app.database import DbSession
from app.models.health_metrics import DailyHealthMetrics
from app.models.plan import Plan
from app.models.queue import WorkoutQueue
from app.models.workout import Workout
from app.routes.schedule import build_calendar
from app.schedule_utils import cycle_end_date

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


def _check_db(db: DbSession) -> bool:
    try:
        db.execute(select(func.count()).select_from(Workout))
        return True
    except Exception:
        return False


@router.get("")
def overview(request: Request, db: DbSession):
    db_ok = _check_db(db)
    settings = get_settings()

    # Stats
    total_workouts = db.scalar(select(func.count()).select_from(Workout)) or 0
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    recent_count = db.scalar(
        select(func.count()).select_from(Workout).where(Workout.start_date >= week_ago)
    ) or 0

    queue_pending = db.scalar(
        select(func.count()).select_from(WorkoutQueue).where(WorkoutQueue.status == "pending")
    ) or 0
    queue_synced = db.scalar(
        select(func.count()).select_from(WorkoutQueue).where(WorkoutQueue.status == "synced")
    ) or 0
    queue_completed = db.scalar(
        select(func.count()).select_from(WorkoutQueue).where(WorkoutQueue.status == "completed")
    ) or 0

    health_days = db.scalar(select(func.count()).select_from(DailyHealthMetrics)) or 0

    # Active plan
    plan_row = db.scalars(
        select(Plan).where(Plan.status == "active").order_by(Plan.created_at.desc())
    ).first()

    plan = None
    if plan_row:
        total_count = db.scalar(
            select(func.count()).select_from(WorkoutQueue).where(WorkoutQueue.plan_id == plan_row.id)
        ) or 0
        completed_count = db.scalar(
            select(func.count()).select_from(WorkoutQueue)
            .where(WorkoutQueue.plan_id == plan_row.id, WorkoutQueue.status == "completed")
        ) or 0
        plan = {
            "name": plan_row.name,
            "start_date": plan_row.start_date,
            "end_date": plan_row.end_date,
            "activity_type": plan_row.activity_type,
            "total_count": total_count,
            "completed_count": completed_count,
            "completion_pct": round(completed_count / total_count * 100) if total_count else 0,
        }

    # Latest health
    latest_health = db.scalars(
        select(DailyHealthMetrics).order_by(DailyHealthMetrics.date.desc()).limit(1)
    ).first()

    # Recent workouts
    recent_workouts = db.scalars(
        select(Workout).order_by(Workout.start_date.desc()).limit(10)
    ).all()

    return templates.TemplateResponse(request, "overview.html", {
        "active_page": "overview",
        "db_ok": db_ok,
        "stats": {
            "total_workouts": total_workouts,
            "recent_workouts": recent_count,
            "queue_pending": queue_pending,
            "queue_synced": queue_synced,
            "queue_completed": queue_completed,
            "health_days": health_days,
        },
        "plan": plan,
        "latest_health": latest_health,
        "recent_workouts": recent_workouts,
    })


@router.get("/plan")
def plan_view(request: Request, db: DbSession):
    db_ok = _check_db(db)

    plan_row = db.scalars(
        select(Plan).where(Plan.status == "active").order_by(Plan.created_at.desc())
    ).first()

    plan = None
    phases = []
    goals = []
    guardrails = []
    workouts = []

    if plan_row:
        # Get plan workouts with inventory dates
        from app.models.inventory import WorkoutInventory

        queue_items = db.scalars(
            select(WorkoutQueue).where(WorkoutQueue.plan_id == plan_row.id).order_by(WorkoutQueue.created_at)
        ).all()

        inventory = {
            str(i.id): i for i in db.scalars(select(WorkoutInventory)).all()
        }

        total_count = len(queue_items)
        completed_count = sum(1 for q in queue_items if q.status == "completed")

        plan = {
            "name": plan_row.name,
            "status": plan_row.status,
            "start_date": plan_row.start_date,
            "end_date": plan_row.end_date,
            "activity_type": plan_row.activity_type,
            "description": plan_row.description,
            "total_count": total_count,
            "completed_count": completed_count,
            "completion_pct": round(completed_count / total_count * 100) if total_count else 0,
        }

        metadata = plan_row.metadata_ or {}

        # Current week
        current_week = (date.today() - plan_row.start_date).days // 7

        raw_phases = metadata.get("phases", [])
        for p in raw_phases:
            phases.append({
                "name": p.get("name", ""),
                "weeks": p.get("weeks", []),
                "volume_target_km": p.get("volume_target_km"),
                "notes": p.get("notes"),
                "is_current": current_week in p.get("weeks", []),
            })

        goals = metadata.get("goals", [])
        guardrails = metadata.get("guardrails", [])

        for q in queue_items:
            scheduled_date = None
            if q.scheduled_date:
                scheduled_date = q.scheduled_date.date().isoformat()
            else:
                inv = inventory.get(str(q.id))
                if inv and inv.year and inv.month and inv.day:
                    scheduled_date = date(inv.year, inv.month, inv.day).isoformat()
            workouts.append({
                "title": q.title,
                "status": q.status,
                "scheduled_date": scheduled_date,
            })

        workouts.sort(key=lambda w: w["scheduled_date"] or "9999")

    return templates.TemplateResponse(request, "plan.html", {
        "active_page": "plan",
        "db_ok": db_ok,
        "plan": plan,
        "phases": phases,
        "goals": goals,
        "guardrails": guardrails,
        "workouts": workouts,
    })


@router.get("/schedule")
def schedule_view(request: Request, db: DbSession):
    db_ok = _check_db(db)
    today = date.today()
    start_monday = today - timedelta(days=today.weekday())
    num_weeks = 5
    end = start_monday + timedelta(days=num_weeks * 7 - 1)

    # Unscoped (all users) until the dashboard gets per-user auth in Phase 3.
    calendar = build_calendar(db, None, start_monday, end)
    by_date: dict[str, list] = {}
    for e in calendar["entries"]:
        by_date.setdefault(e["date"], []).append(e)

    weeks = []
    for w in range(num_weeks):
        wk_monday = start_monday + timedelta(days=7 * w)
        days = []
        for i in range(7):
            d = wk_monday + timedelta(days=i)
            days.append({
                "dow": d.strftime("%a"),
                "day_num": d.day,
                "is_today": d == today,
                "is_past": d < today,
                "entries": by_date.get(d.isoformat(), []),
            })
        weeks.append({"label": wk_monday.strftime("%b %d").lstrip("0"), "days": days})

    conflict_count = sum(1 for e in calendar["entries"] if e["conflict"]) // 2

    # Active recurring cycles + their horizon (the "when do I renew?" signal)
    cycles = []
    active_plans = db.scalars(
        select(Plan).where(Plan.status == "active").order_by(Plan.created_at.desc())
    ).all()
    for plan in active_plans:
        schedule = (plan.metadata_ or {}).get("schedule")
        if not schedule:
            continue
        cycle_end = cycle_end_date(schedule)
        cycles.append({
            "name": plan.name,
            "activity_type": plan.activity_type,
            "days": schedule.get("days", {}),
            "weeks": schedule.get("weeks"),
            "end_date": cycle_end,
            "days_left": (cycle_end - today).days if cycle_end else None,
        })

    return templates.TemplateResponse(request, "schedule.html", {
        "active_page": "schedule",
        "db_ok": db_ok,
        "weeks": weeks,
        "conflict_count": conflict_count,
        "cycles": cycles,
        "has_entries": bool(calendar["entries"]),
    })


@router.get("/settings")
def settings_view(request: Request, db: DbSession):
    db_ok = _check_db(db)
    settings = get_settings()

    api_key = settings.api_key
    masked_key = api_key[:4] + "•" * (len(api_key) - 8) + api_key[-4:] if len(api_key) > 8 else "•" * len(api_key)

    endpoints = [
        {"method": "GET", "path": "/api/health", "desc": "Health check"},
        {"method": "GET", "path": "/api/workouts", "desc": "List workouts"},
        {"method": "POST", "path": "/api/workouts", "desc": "Create/upsert workout"},
        {"method": "GET", "path": "/api/workouts/{id}", "desc": "Get workout detail"},
        {"method": "GET", "path": "/api/workouts/{id}/splits", "desc": "Get workout splits"},
        {"method": "GET", "path": "/api/workouts/{id}/heartrate", "desc": "Get heart rate data"},
        {"method": "DELETE", "path": "/api/workouts/{id}", "desc": "Delete workout"},
        {"method": "GET", "path": "/api/workouts/summary", "desc": "Training summary"},
        {"method": "GET", "path": "/api/workouts/queue", "desc": "Pending queue (app-facing)"},
        {"method": "DELETE", "path": "/api/workouts/queue/{id}", "desc": "Mark queue item synced"},
        {"method": "GET", "path": "/api/workouts/actions", "desc": "Pending actions"},
        {"method": "POST", "path": "/api/workouts/actions", "desc": "Create action"},
        {"method": "GET", "path": "/api/workouts/feedback", "desc": "Workout feedback"},
        {"method": "POST", "path": "/api/workouts/feedback", "desc": "Submit feedback"},
        {"method": "GET", "path": "/api/workouts/inventory", "desc": "Device inventory"},
        {"method": "PUT", "path": "/api/workouts/inventory", "desc": "Sync inventory"},
        {"method": "GET", "path": "/api/queue", "desc": "List all queue items"},
        {"method": "POST", "path": "/api/queue", "desc": "Create queue item"},
        {"method": "POST", "path": "/api/queue/batch", "desc": "Batch create queue items"},
        {"method": "PATCH", "path": "/api/queue/{id}", "desc": "Update queue item"},
        {"method": "DELETE", "path": "/api/queue/{id}", "desc": "Delete queue item"},
        {"method": "GET", "path": "/api/plans", "desc": "List plans"},
        {"method": "POST", "path": "/api/plans", "desc": "Create plan"},
        {"method": "GET", "path": "/api/plans/{id}", "desc": "Get plan"},
        {"method": "PATCH", "path": "/api/plans/{id}", "desc": "Update plan"},
        {"method": "DELETE", "path": "/api/plans/{id}", "desc": "Delete plan"},
        {"method": "GET", "path": "/api/plans/{id}/workouts", "desc": "Plan workouts"},
        {"method": "GET", "path": "/api/plans/{id}/schedule", "desc": "Get recurring schedule + conflicts"},
        {"method": "PUT", "path": "/api/plans/{id}/schedule", "desc": "Set recurring schedule"},
        {"method": "DELETE", "path": "/api/plans/{id}/schedule", "desc": "Clear recurring schedule"},
        {"method": "GET", "path": "/api/schedule/calendar", "desc": "Unified run + strength calendar"},
        {"method": "POST", "path": "/api/health/metrics", "desc": "Bulk upsert health metrics"},
        {"method": "GET", "path": "/api/health/metrics", "desc": "Query health metrics"},
    ]

    db_uri = settings.db_uri
    db_host = "db (docker)" if "db" in db_uri else db_uri.split("@")[-1].split("/")[0] if "@" in db_uri else "unknown"
    db_name = db_uri.split("/")[-1] if "/" in db_uri else "unknown"

    return templates.TemplateResponse(request, "settings.html", {
        "active_page": "settings",
        "db_ok": db_ok,
        "masked_key": masked_key,
        "db_host": db_host,
        "db_name": db_name,
        "version": "0.1.0",
        "endpoints": endpoints,
    })
