import os
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI
from fastapi.responses import FileResponse, JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.auth import get_current_user
from app.rate_limit import limiter
from app.routes import actions, admin, auth, feedback, health, health_metrics, inventory, plan_notes, plans, queue, schedule, workouts

app = FastAPI(title="Training API", version="0.1.0")

# React dashboard build (frontend/dist), baked into the image at /app/static.
# Served same-origin so the existing Tailscale Funnel setup needs no CORS.
# Absent in local dev, where Vite serves the frontend and proxies /api here.
SPA_DIST = Path(os.environ.get("SPA_DIST", "static")).resolve()
SPA_INDEX = SPA_DIST / "index.html"

# Rate limiting (used by /api/auth/login)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# The server-rendered dashboard is DISABLED. It was unauthenticated and served
# personal data (health metrics, workouts, plans) over the public Tailscale
# Funnel, and is being replaced by a separate authenticated frontend. The routes
# and templates remain in app/routes/dashboard.py + app/templates/ for reference
# — do NOT re-mount without auth, it would re-expose that data. See
# docs/multi-user-plan.md (Phase 3).


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
