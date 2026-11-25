"""Fuelling: what the athlete drinks and eats on a workout, and plans to.

Three things, all entered by hand (this is separate from the nutrition sync,
which is daily totals read from Health):

- saved products (`/api/fuel/products`): a gel, a drink mix, saved once;
- the log on a recorded workout (`/api/workouts/{id}/fuel`);
- the plan on a planned session (`/api/workouts/queue/{id}/fuel`).

A workout shows its plan next to its log: the plan is the one on the session
the workout counts for (`plan_workout_id`).

Shared with the coach under the `nutrition` consent domain: a consent-scoped
caller (the MCP) gets a 403 when the athlete does not share it. The app and
dashboard are never filtered.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.auth import CurrentUser
from app.data_consent import NUTRITION, CurrentConsent
from app.database import DbSession
from app.models.fuel import FuelEntry, FuelProduct
from app.models.queue import WorkoutQueue
from app.models.workout import Workout
from app.schemas.fuel import (
    MAX_ENTRIES,
    EntriesReplace,
    EntryIn,
    FuelHistoryItem,
    FuelSummary,
    ProductCreate,
    ProductOut,
    ProductUpdate,
    SessionFuelOut,
    WorkoutFuelOut,
)
from app.tenancy import get_owned


def _require_shared(consent: CurrentConsent) -> None:
    consent.require(NUTRITION)


_shared = [Depends(_require_shared)]

# Mounted at /fuel, /workouts and /workouts/queue.
router = APIRouter(dependencies=_shared)
workout_router = APIRouter(dependencies=_shared)
session_router = APIRouter(dependencies=_shared)

# Below this a per-hour rate says more about the rounding than the run.
MIN_RATE_SECONDS = 20 * 60


# ── products ────────────────────────────────────────────────────────────────


@router.get("/products", response_model=list[ProductOut])
def list_products(db: DbSession, user: CurrentUser):
    """Every saved product: drinks first, then by name."""
    return db.scalars(
        select(FuelProduct)
        .where(FuelProduct.user_id == user.id)
        .order_by(FuelProduct.kind != "drink", func.lower(FuelProduct.name))
    ).all()


@router.post("/products", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(payload: ProductCreate, db: DbSession, user: CurrentUser):
    product = FuelProduct(
        user_id=user.id,
        name=payload.name,
        kind=payload.kind,
        # Only a drink has a serving volume.
        volume_ml=payload.volume_ml if payload.kind == "drink" else None,
        carbs_g=payload.carbs_g,
        caffeine_mg=payload.caffeine_mg,
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@router.patch("/products/{product_id}", response_model=ProductOut)
def update_product(product_id: uuid.UUID, payload: ProductUpdate, db: DbSession, user: CurrentUser):
    product = get_owned(db, FuelProduct, product_id, user)
    sent = payload.model_fields_set
    if "name" in sent and payload.name is not None:
        product.name = payload.name
    if "kind" in sent and payload.kind is not None:
        product.kind = payload.kind
    for field in ("volume_ml", "carbs_g", "caffeine_mg"):
        if field in sent:
            setattr(product, field, getattr(payload, field))
    if product.kind != "drink":
        product.volume_ml = None
    db.commit()
    db.refresh(product)
    return product


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(product_id: uuid.UUID, db: DbSession, user: CurrentUser):
    """Removes the product. What was logged or planned with it stays, with
    the name and figures it had."""
    db.delete(get_owned(db, FuelProduct, product_id, user))
    db.commit()


# ── entries ─────────────────────────────────────────────────────────────────


def _ordered(entries: list[FuelEntry]) -> list[FuelEntry]:
    """Drinks first, then everything else in the order it was taken; what has
    no position keeps the order it was sent in, after what has one."""
    return sorted(
        entries,
        key=lambda e: (e.kind != "drink", e.at_distance is None, e.at_distance or 0.0, e.position),
    )


def _entries(db: Session, user, *, workout_id: uuid.UUID | None = None, queue_item_id: uuid.UUID | None = None):
    q = select(FuelEntry).where(FuelEntry.user_id == user.id)
    q = q.where(FuelEntry.workout_id == workout_id) if workout_id else q.where(FuelEntry.queue_item_id == queue_item_id)
    return _ordered(list(db.scalars(q).all()))


def _summary(entries: list[FuelEntry], duration: float | None = None) -> FuelSummary:
    volume = sum(e.volume_ml or 0.0 for e in entries)
    carbs = sum(e.carbs_g or 0.0 for e in entries)
    caffeine = sum(e.caffeine_mg or 0.0 for e in entries)
    hours = duration / 3600 if duration and duration >= MIN_RATE_SECONDS else None
    return FuelSummary(
        volume_ml=round(volume, 1),
        carbs_g=round(carbs, 1),
        caffeine_mg=round(caffeine, 1),
        carbs_per_hour_g=round(carbs / hours, 1) if hours else None,
        fluid_per_hour_ml=round(volume / hours) if hours else None,
    )


def _resolve(db: Session, user, payload: EntryIn, position: int, **owner) -> FuelEntry:
    """The row for one entry as sent, with what it left out taken from its
    product."""
    product = None
    if payload.product_id is not None:
        product = db.get(FuelProduct, payload.product_id)
        if product is None or product.user_id != user.id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Unknown productId {payload.product_id}")

    name = payload.name or (product.name if product else None)
    kind = payload.kind or (product.kind if product else None)
    if not name or not kind:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="An entry needs a productId, or a name and a kind"
        )

    sent = payload.model_fields_set
    volume = payload.volume_ml
    if volume is None and product is not None and kind == "drink":
        volume = product.volume_ml

    # A drink's figures are per serving, so they follow the volume drunk.
    share = 1.0
    if product is not None and kind == "drink" and product.volume_ml and volume:
        share = volume / product.volume_ml

    def figure(field: str) -> float | None:
        if field in sent:
            return getattr(payload, field)
        per_serving = getattr(product, field) if product is not None else None
        return None if per_serving is None else round(per_serving * share, 1)

    return FuelEntry(
        user_id=user.id,
        product_id=product.id if product else None,
        name=name,
        kind=kind,
        volume_ml=volume,
        carbs_g=figure("carbs_g"),
        caffeine_mg=figure("caffeine_mg"),
        at_distance=payload.at_distance,
        position=position,
        **owner,
    )


def _replace(db: Session, user, payloads: list[EntryIn], **owner) -> None:
    # Resolve first: a bad entry must not leave the list emptied.
    rows = [_resolve(db, user, payload, position, **owner) for position, payload in enumerate(payloads)]
    column, value = next(iter(owner.items()))
    db.execute(delete(FuelEntry).where(FuelEntry.user_id == user.id, getattr(FuelEntry, column) == value))
    db.add_all(rows)
    db.commit()


def _append(db: Session, user, payload: EntryIn, existing: list[FuelEntry], **owner) -> None:
    if len(existing) >= MAX_ENTRIES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"A list holds at most {MAX_ENTRIES} entries"
        )
    position = max((e.position for e in existing), default=-1) + 1
    db.add(_resolve(db, user, payload, position, **owner))
    db.commit()


def _workout_fuel(db: Session, user, workout: Workout) -> dict:
    entries = _entries(db, user, workout_id=workout.id)
    planned = _entries(db, user, queue_item_id=workout.plan_workout_id) if workout.plan_workout_id else []
    return {
        "entries": entries,
        "summary": _summary(entries, workout.duration),
        "planned": planned,
        # The plan's rates use the workout's duration too, so the two compare.
        "planned_summary": _summary(planned, workout.duration) if planned else None,
        "planned_session_id": workout.plan_workout_id if planned else None,
    }


# ── a workout's log ─────────────────────────────────────────────────────────


@workout_router.get("/{workout_id}/fuel", response_model=WorkoutFuelOut)
def get_workout_fuel(workout_id: uuid.UUID, db: DbSession, user: CurrentUser):
    """What was drunk and eaten on a workout, and the plan it had."""
    return _workout_fuel(db, user, get_owned(db, Workout, workout_id, user))


@workout_router.put("/{workout_id}/fuel", response_model=WorkoutFuelOut)
def replace_workout_fuel(workout_id: uuid.UUID, payload: EntriesReplace, db: DbSession, user: CurrentUser):
    """Replace the whole log. An empty list clears it."""
    workout = get_owned(db, Workout, workout_id, user)
    _replace(db, user, payload.entries, workout_id=workout.id)
    return _workout_fuel(db, user, workout)


@workout_router.post("/{workout_id}/fuel", response_model=WorkoutFuelOut, status_code=status.HTTP_201_CREATED)
def add_workout_fuel(workout_id: uuid.UUID, payload: EntryIn, db: DbSession, user: CurrentUser):
    """Add one entry to the log."""
    workout = get_owned(db, Workout, workout_id, user)
    _append(db, user, payload, _entries(db, user, workout_id=workout.id), workout_id=workout.id)
    return _workout_fuel(db, user, workout)


# ── a session's plan ────────────────────────────────────────────────────────


def _session_fuel(db: Session, user, item: WorkoutQueue) -> dict:
    entries = _entries(db, user, queue_item_id=item.id)
    return {"entries": entries, "summary": _summary(entries)}


@session_router.get("/{item_id}/fuel", response_model=SessionFuelOut)
def get_session_fuel(item_id: uuid.UUID, db: DbSession, user: CurrentUser):
    """The fuelling plan on a planned session."""
    return _session_fuel(db, user, get_owned(db, WorkoutQueue, item_id, user))


@session_router.put("/{item_id}/fuel", response_model=SessionFuelOut)
def replace_session_fuel(item_id: uuid.UUID, payload: EntriesReplace, db: DbSession, user: CurrentUser):
    """Replace the whole plan. An empty list clears it."""
    item = get_owned(db, WorkoutQueue, item_id, user)
    _replace(db, user, payload.entries, queue_item_id=item.id)
    return _session_fuel(db, user, item)


@session_router.post("/{item_id}/fuel", response_model=SessionFuelOut, status_code=status.HTTP_201_CREATED)
def add_session_fuel(item_id: uuid.UUID, payload: EntryIn, db: DbSession, user: CurrentUser):
    """Add one entry to the plan."""
    item = get_owned(db, WorkoutQueue, item_id, user)
    _append(db, user, payload, _entries(db, user, queue_item_id=item.id), queue_item_id=item.id)
    return _session_fuel(db, user, item)


# ── across workouts ─────────────────────────────────────────────────────────


@router.get("/history", response_model=list[FuelHistoryItem])
def fuel_history(db: DbSession, user: CurrentUser, limit: int = Query(default=10, ge=1, le=50)):
    """The most recent workouts with a fuelling log, newest first, each with
    its log and the plan it had."""
    logged = select(FuelEntry.workout_id).where(FuelEntry.user_id == user.id, FuelEntry.workout_id.is_not(None))
    workouts = db.scalars(
        select(Workout)
        .where(Workout.user_id == user.id, Workout.id.in_(logged))
        .order_by(Workout.start_date.desc())
        .limit(limit)
    ).all()
    return [
        {
            **_workout_fuel(db, user, workout),
            "workout_id": workout.id,
            "activity_type": workout.activity_type,
            "start_date": workout.start_date,
            "duration": workout.duration,
            "total_distance": workout.total_distance,
        }
        for workout in workouts
    ]
