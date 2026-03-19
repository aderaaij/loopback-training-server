import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.database import DbSession
from app.models.action import WorkoutAction
from app.schemas.action import ActionCreate, ActionRead

router = APIRouter()


@router.get("", response_model=list[ActionRead])
def get_pending_actions(db: DbSession):
    q = select(WorkoutAction).order_by(WorkoutAction.created_at)
    return db.scalars(q).all()


@router.post("", response_model=ActionRead, status_code=status.HTTP_201_CREATED)
def create_action(payload: ActionCreate, db: DbSession):
    action = WorkoutAction(
        workout_id=payload.workout_id,
        action=payload.action,
        composition=payload.composition,
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    return action


@router.post("/batch", response_model=list[ActionRead], status_code=status.HTTP_201_CREATED)
def create_actions_batch(payload: list[ActionCreate], db: DbSession):
    actions = []
    for item in payload:
        action = WorkoutAction(
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
def acknowledge_action(action_id: uuid.UUID, db: DbSession):
    action = db.get(WorkoutAction, action_id)
    if not action:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Action not found")
    db.delete(action)
    db.commit()
    return {"ok": True}
