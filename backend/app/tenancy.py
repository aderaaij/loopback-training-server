"""Helpers for per-user data scoping.

`get_owned` replaces the ~20 bare ``db.get(Model, id)`` primary-key lookups: it
returns the row only if it belongs to the caller, and 404s (never 403 — don't
reveal that another user's row exists) otherwise.
"""

import uuid
from typing import TypeVar

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.user import User

T = TypeVar("T")


def get_owned(db: Session, model: type[T], obj_id: uuid.UUID, user: User) -> T:
    obj = db.get(model, obj_id)
    if obj is None or obj.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{model.__name__} not found")
    return obj
