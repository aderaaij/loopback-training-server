"""Shoe tracking: pairs of running shoes and the distance on each.

camelCase on the wire, like the other endpoints the app added recently.
Distances are meters throughout; clients convert for display.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel
from sqlalchemy import func, select, update

from app.auth import CurrentUser
from app.database import DbSession
from app.models.shoe import Shoe
from app.models.workout import Workout
from app.tenancy import get_owned

router = APIRouter()


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


def _clean_name(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("name must not be blank")
    return value


class ShoeCreate(_CamelModel):
    name: str = Field(max_length=120)
    start_distance: float = Field(default=0, ge=0)
    target_distance: float | None = Field(default=None, gt=0)
    is_default: bool = False

    _name = field_validator("name")(_clean_name)


class ShoeUpdate(_CamelModel):
    """Only the fields present are changed. `targetDistance: null` removes
    the target; `retired` true/false retires the pair or brings it back."""

    name: str | None = Field(default=None, max_length=120)
    start_distance: float | None = Field(default=None, ge=0)
    target_distance: float | None = Field(default=None, gt=0)
    is_default: bool | None = None
    retired: bool | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        return None if value is None else _clean_name(value)


class ShoeOut(_CamelModel):
    id: uuid.UUID
    name: str
    start_distance: float
    target_distance: float | None
    is_default: bool
    retired_at: datetime | None
    created_at: datetime
    # start_distance plus every assigned workout's distance.
    distance: float
    workout_count: int
    last_used_at: datetime | None


def _usage(db: DbSession, user) -> dict[uuid.UUID, tuple[int, float, datetime | None]]:
    rows = db.execute(
        select(
            Workout.shoe_id,
            func.count(Workout.id),
            func.coalesce(func.sum(Workout.total_distance), 0.0),
            func.max(Workout.start_date),
        )
        .where(Workout.user_id == user.id, Workout.shoe_id.is_not(None))
        .group_by(Workout.shoe_id)
    ).all()
    return {shoe_id: (count, float(total), last) for shoe_id, count, total, last in rows}


def _out(shoe: Shoe, usage: dict) -> ShoeOut:
    count, total, last = usage.get(shoe.id, (0, 0.0, None))
    return ShoeOut(
        id=shoe.id,
        name=shoe.name,
        start_distance=shoe.start_distance,
        target_distance=shoe.target_distance,
        is_default=shoe.is_default,
        retired_at=shoe.retired_at,
        created_at=shoe.created_at,
        distance=round(shoe.start_distance + total, 1),
        workout_count=count,
        last_used_at=last,
    )


def _clear_default(db: DbSession, user, keep: uuid.UUID | None = None) -> None:
    """One default per user. Flushed before the new one is set, so the unique
    index never sees two."""
    q = update(Shoe).where(Shoe.user_id == user.id, Shoe.is_default.is_(True))
    if keep is not None:
        q = q.where(Shoe.id != keep)
    db.execute(q.values(is_default=False))


@router.get("", response_model=list[ShoeOut])
def list_shoes(db: DbSession, user: CurrentUser):
    """Every pair, in use first (newest first), then retired."""
    shoes = db.scalars(
        select(Shoe)
        .where(Shoe.user_id == user.id)
        .order_by(Shoe.retired_at.is_not(None), Shoe.created_at.desc())
    ).all()
    usage = _usage(db, user)
    return [_out(shoe, usage) for shoe in shoes]


@router.post("", response_model=ShoeOut, status_code=status.HTTP_201_CREATED)
def create_shoe(payload: ShoeCreate, db: DbSession, user: CurrentUser):
    if payload.is_default:
        _clear_default(db, user)
    shoe = Shoe(
        user_id=user.id,
        name=payload.name,
        start_distance=payload.start_distance,
        target_distance=payload.target_distance,
        is_default=payload.is_default,
    )
    db.add(shoe)
    db.commit()
    db.refresh(shoe)
    return _out(shoe, {})


@router.patch("/{shoe_id}", response_model=ShoeOut)
def update_shoe(shoe_id: uuid.UUID, payload: ShoeUpdate, db: DbSession, user: CurrentUser):
    shoe = get_owned(db, Shoe, shoe_id, user)
    sent = payload.model_fields_set

    if "name" in sent and payload.name is not None:
        shoe.name = payload.name
    if "start_distance" in sent and payload.start_distance is not None:
        shoe.start_distance = payload.start_distance
    if "target_distance" in sent:
        shoe.target_distance = payload.target_distance
    if "retired" in sent and payload.retired is not None:
        if payload.retired and shoe.retired_at is None:
            shoe.retired_at = func.now()
            # New runs must not keep landing on a pair that is put away.
            shoe.is_default = False
        elif not payload.retired:
            shoe.retired_at = None
    if "is_default" in sent and payload.is_default is not None:
        if payload.is_default:
            if shoe.retired_at is not None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="A retired pair can't be the default",
                )
            _clear_default(db, user, keep=shoe.id)
        shoe.is_default = payload.is_default

    db.commit()
    db.refresh(shoe)
    return _out(shoe, _usage(db, user))


@router.delete("/{shoe_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_shoe(shoe_id: uuid.UUID, db: DbSession, user: CurrentUser):
    """Removes the pair. Its workouts stay, without a pair."""
    shoe = get_owned(db, Shoe, shoe_id, user)
    db.delete(shoe)
    db.commit()
