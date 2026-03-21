from fastapi import APIRouter, Depends, FastAPI

from app.auth import verify_api_key
from app.routes import actions, feedback, health, inventory, queue, workouts

app = FastAPI(title="Training API", version="0.1.0")

# Health endpoint — no auth
app.include_router(health.router, prefix="/api", tags=["health"])

# Authenticated routes
api_router = APIRouter(prefix="/api", dependencies=[Depends(verify_api_key)])
api_router.include_router(queue.workout_queue_router, prefix="/workouts/queue", tags=["queue"])
api_router.include_router(actions.router, prefix="/workouts/actions", tags=["actions"])
api_router.include_router(feedback.router, prefix="/workouts/feedback", tags=["feedback"])
api_router.include_router(inventory.router, prefix="/workouts/inventory", tags=["inventory"])
api_router.include_router(workouts.router, prefix="/workouts", tags=["workouts"])
api_router.include_router(queue.router, prefix="/queue", tags=["queue"])
app.include_router(api_router)
