import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.auth import CurrentUser
from app.database import DbSession
from app.models.action import WorkoutAction
from app.models.queue import WorkoutQueue
from app.routes.queue import _scheduled_date_from_data
from app.schemas.action import ActionCreate, ActionRead
from app.tenancy import get_owned

router = APIRouter()


@router.get("", response_model=list[ActionRead])
def get_pending_actions(db: DbSession, user: CurrentUser):
    q = select(WorkoutAction).where(WorkoutAction.user_id == user.id).order_by(WorkoutAction.created_at)
    return db.scalars(q).all()


@router.post("", response_model=ActionRead, status_code=status.HTTP_201_CREATED)
def create_action(payload: ActionCreate, db: DbSession, user: CurrentUser):
    action = WorkoutAction(
        user_id=user.id,
        workout_id=payload.workout_id,
        action=payload.action,
        composition=payload.composition,
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    return action


@router.post("/batch", response_model=list[ActionRead], status_code=status.HTTP_201_CREATED)
def create_actions_batch(payload: list[ActionCreate], db: DbSession, user: CurrentUser):
    actions = []
    for item in payload:
        action = WorkoutAction(
            user_id=user.id,
            workout_id=item.workout_id,
            action=item.action,
            composition=item.composition,
        )
        db.add(action)
        actions.append(action)
    db.commit()
    for action in actions:
        db.refresh(action)
    return actions


@router.delete("/{action_id}", status_code=status.HTTP_200_OK)
def acknowledge_action(action_id: uuid.UUID, db: DbSession, user: CurrentUser):
    action = get_owned(db, WorkoutAction, action_id, user)
    # The app acks an action only after applying it on the watch — mirror the
    # confirmed change onto the queue item so validation, /context, and future
    # edits don't keep reading pre-action state.
    item = db.get(WorkoutQueue, action.workout_id)
    if item is not None and item.user_id == user.id:
        if action.action == "edit" and action.composition is not None:
            item.workout_data = action.composition
            item.scheduled_date = _scheduled_date_from_data(action.composition) or item.scheduled_date
        elif action.action == "delete" and item.status != "completed":
            # Removed from the watch: retire the item like a skipped session
            # so it stops counting as a scheduled run or schedule collision.
            item.status = "skipped"
    db.delete(action)
    db.commit()
    return {"ok": True}
