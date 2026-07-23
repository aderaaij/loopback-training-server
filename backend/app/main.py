import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.auth import get_current_user
from app.auth_events import client_ip, record_auth_event
from app.backup import run_scheduler
from app.database import SessionLocal
from app.rate_limit import limiter
from app.routes import actions, admin, auth, feedback, health, health_metrics, inventory, plan_notes, plans, queue, schedule, sleep, workouts
from app.version import __version__


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Nightly-backup scheduler; exits on its own when backups are disabled or
    # the backup dir isn't writable (see app/backup.py).
    backup_task = asyncio.create_task(run_scheduler())
    yield
    backup_task.cancel()
    with suppress(asyncio.CancelledError):
        await backup_task


app = FastAPI(title="Training API", version=__version__, lifespan=lifespan)

# React dashboard build (frontend/dist), baked into the image at /app/static.
# Served same-origin so the existing Tailscale Funnel setup needs no CORS.
# Absent in local dev, where Vite serves the frontend and proxies /api here.
SPA_DIST = Path(os.environ.get("SPA_DIST", "static")).resolve()
SPA_INDEX = SPA_DIST / "index.html"

# Rate limiting (used by /api/auth/login)
app.state.limiter = limiter


# The login endpoint is publicly reachable (Tailscale Funnel), so a hammered
# rate limit must not translate every 429 into a DB write: audit at most one
# event per IP per window, tracked in-process.
_RL_EVENT_WINDOW_S = 60.0
_rl_event_last: dict[str, float] = {}


def _rate_limited(request: Request, exc: Exception):
    ip = client_ip(request)
    now = time.monotonic()
    last = _rl_event_last.get(ip or "")
    if last is None or now - last >= _RL_EVENT_WINDOW_S:
        if len(_rl_event_last) > 1024:  # bound the map under a many-IP flood
            _rl_event_last.clear()
        _rl_event_last[ip or ""] = now
        try:
            # The route's own DB session is unusable here (the request never
            # entered the route), so the audit row gets its own session.
            with SessionLocal() as db:
                record_auth_event(db, "login_rate_limited", ip=ip, commit=True)
        except Exception:
            # Auditing must never turn a 429 into a 500.
            logging.getLogger("uvicorn.error").exception("failed to record login_rate_limited")
    return _rate_limit_exceeded_handler(request, exc)  # type: ignore[arg-type]


app.add_exception_handler(RateLimitExceeded, _rate_limited)

# The old unauthenticated server-rendered dashboard was removed 2026-07-18
# (replaced by the authenticated SPA below); it lives on in git history only.


@app.get("/", include_in_schema=False)
def root():
    if SPA_INDEX.is_file():
        return FileResponse(SPA_INDEX)
    return {"service": "training-api", "status": "ok"}


# Health endpoint — no auth
app.include_router(health.router, prefix="/api", tags=["health"])

# Auth endpoints — login is public; me/revoke self-enforce via CurrentUser
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])

# Authenticated routes
api_router = APIRouter(prefix="/api", dependencies=[Depends(get_current_user)])
api_router.include_router(queue.workout_queue_router, prefix="/workouts/queue", tags=["queue"])
api_router.include_router(actions.router, prefix="/workouts/actions", tags=["actions"])
api_router.include_router(feedback.router, prefix="/workouts/feedback", tags=["feedback"])
api_router.include_router(inventory.router, prefix="/workouts/inventory", tags=["inventory"])
api_router.include_router(workouts.router, prefix="/workouts", tags=["workouts"])
api_router.include_router(queue.router, prefix="/queue", tags=["queue"])
api_router.include_router(health_metrics.router, prefix="/health/metrics", tags=["health-metrics"])
api_router.include_router(sleep.router, prefix="/health/sleep", tags=["sleep"])
api_router.include_router(plans.router, prefix="/plans", tags=["plans"])
api_router.include_router(plan_notes.router, prefix="/plan-notes", tags=["plan-notes"])
api_router.include_router(schedule.router, prefix="/schedule", tags=["schedule"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
app.include_router(api_router)


# SPA catch-all — registered last, so it only sees paths no API route matched.
# Real build files (assets/, favicon) are served as-is; anything else gets
# index.html so client-side routes like /workouts/<id> deep-link correctly.
@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    if full_path.startswith("api/") or not SPA_INDEX.is_file():
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    candidate = (SPA_DIST / full_path).resolve()
    if candidate.is_file() and candidate.is_relative_to(SPA_DIST):
        return FileResponse(candidate)
    return FileResponse(SPA_INDEX)
