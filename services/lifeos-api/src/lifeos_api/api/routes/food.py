from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifeos_api.api.deps import get_session
from lifeos_api.core.time import lifeos_today
from lifeos_api.domain.food import (
    FOOD_LOG_STATUSES,
    FoodLogNotFoundError,
    build_food_daily_summary,
    build_food_progress_context,
    create_food_target,
    food_log_item_from_payload,
    get_food_log_or_404,
    get_or_create_active_food_target,
)
from lifeos_api.models import AdviceLog, FoodDailyReview, FoodLog
from lifeos_api.schemas import (
    FoodDailyReviewCreate,
    FoodLogCreate,
    FoodLogItemPayload,
    FoodLogUpdate,
    FoodTargetRecalculate,
)
from lifeos_api.seed import get_or_create_user
from lifeos_api.serializers import food_daily_review_to_dict, food_log_to_dict, food_target_to_dict
from lifeos_api.utils import slugify

router = APIRouter()


@router.get("/food/target")
def get_food_target(session: Session = Depends(get_session)) -> dict[str, Any]:
    user, _ = get_or_create_user(session)
    target = get_or_create_active_food_target(session, user.id)
    session.commit()
    session.refresh(target)
    return food_target_to_dict(target)


@router.post("/food/target/recalculate", status_code=status.HTTP_201_CREATED)
def recalculate_food_target(payload: FoodTargetRecalculate, session: Session = Depends(get_session)) -> dict[str, Any]:
    user, _ = get_or_create_user(session)
    effective_date = payload.effective_date or lifeos_today()
    target = create_food_target(
        session,
        user.id,
        effective_date,
        calories_override=payload.calories,
        protein_override=payload.protein_g,
        notes=payload.notes,
        archive_existing=True,
    )
    output = food_target_to_dict(target)
    session.add(
        AdviceLog(
            user_id=user.id,
            advice_type="food_target_recalculation",
            input_payload=payload.model_dump(mode="json"),
            output_payload=jsonable_encoder(output),
        )
    )
    session.commit()
    session.refresh(target)
    return food_target_to_dict(target)


@router.post("/food/logs", status_code=status.HTTP_201_CREATED)
def create_food_log(payload: FoodLogCreate, session: Session = Depends(get_session)) -> dict[str, Any]:
    user, _ = get_or_create_user(session)
    get_or_create_active_food_target(session, user.id, payload.log_date)
    food_log = FoodLog(
        user_id=user.id,
        log_date=payload.log_date,
        meal_type=slugify(payload.meal_type),
        status="active",
        source=payload.source,
        description=payload.description,
        calories=payload.calories,
        protein_g=payload.protein_g,
        carbs_g=payload.carbs_g,
        fat_g=payload.fat_g,
        confidence=payload.confidence,
        telegram_metadata=jsonable_encoder(payload.telegram_metadata),
        notes=payload.notes,
    )
    food_log.items = [food_log_item_from_payload(item) for item in payload.items]
    session.add(food_log)
    session.commit()
    session.refresh(food_log)
    return food_log_to_dict(food_log)


@router.patch("/food/logs/{food_log_id}")
def update_food_log(
    food_log_id: int,
    payload: FoodLogUpdate,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    user, _ = get_or_create_user(session)
    try:
        food_log = get_food_log_or_404(session, user.id, food_log_id)
    except FoodLogNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="food log not found") from exc
    updates = payload.model_dump(exclude_unset=True)
    items = updates.pop("items", None)
    if (
        "status" in updates
        and updates["status"] is not None
        and updates["status"] not in FOOD_LOG_STATUSES
    ):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid food log status")
    if "meal_type" in updates and updates["meal_type"] is not None:
        updates["meal_type"] = slugify(updates["meal_type"])
    if "telegram_metadata" in updates and updates["telegram_metadata"] is not None:
        updates["telegram_metadata"] = jsonable_encoder(updates["telegram_metadata"])
    for field, value in updates.items():
        setattr(food_log, field, value)
    if items is not None:
        food_log.items = [food_log_item_from_payload(FoodLogItemPayload.model_validate(item)) for item in items]
    session.commit()
    session.refresh(food_log)
    return food_log_to_dict(food_log)


@router.get("/food/daily-summary")
def get_food_daily_summary(summary_date: date | None = None, session: Session = Depends(get_session)) -> dict[str, Any]:
    user, _ = get_or_create_user(session)
    effective_date = summary_date or lifeos_today()
    target = get_or_create_active_food_target(session, user.id, effective_date)
    session.commit()
    return build_food_daily_summary(session, user.id, effective_date, target)


@router.get("/food/progress")
def get_food_progress(reference_date: date | None = None, session: Session = Depends(get_session)) -> dict[str, Any]:
    user, _ = get_or_create_user(session)
    effective_date = reference_date or lifeos_today()
    target = get_or_create_active_food_target(session, user.id, effective_date)
    session.commit()
    return build_food_progress_context(session, user.id, effective_date, target)


@router.post("/food/reviews/daily", status_code=status.HTTP_201_CREATED)
def create_food_daily_review(payload: FoodDailyReviewCreate, session: Session = Depends(get_session)) -> dict[str, Any]:
    user, _ = get_or_create_user(session)
    review = session.scalar(
        select(FoodDailyReview).where(
            FoodDailyReview.user_id == user.id,
            FoodDailyReview.review_date == payload.review_date,
        )
    )
    if review is None:
        review = FoodDailyReview(user_id=user.id, review_date=payload.review_date)
        session.add(review)
    review.hunger = payload.hunger
    review.energy = payload.energy
    review.adherence_status = payload.adherence_status
    review.notes = payload.notes
    review.recommendations = payload.recommendations
    session.commit()
    session.refresh(review)
    return food_daily_review_to_dict(review)
