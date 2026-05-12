from __future__ import annotations

from typing import Any

from lifeos_api.models import FoodDailyReview, FoodLog, FoodLogItem, FoodTarget
from lifeos_api.utils import rounded_metric


def food_target_to_dict(target: FoodTarget) -> dict[str, Any]:
    return {
        "id": target.id,
        "start_date": target.start_date,
        "end_date": target.end_date,
        "status": target.status,
        "calories": target.calories,
        "protein_g": rounded_metric(float(target.protein_g)),
        "carbs_g": rounded_metric(float(target.carbs_g)) if target.carbs_g is not None else None,
        "fat_g": rounded_metric(float(target.fat_g)) if target.fat_g is not None else None,
        "calorie_floor": target.calorie_floor,
        "source": target.source,
        "calculation": target.calculation,
        "notes": target.notes,
        "created_at": target.created_at,
        "updated_at": target.updated_at,
    }


def food_log_to_dict(food_log: FoodLog) -> dict[str, Any]:
    return {
        "id": food_log.id,
        "log_date": food_log.log_date,
        "meal_type": food_log.meal_type,
        "status": food_log.status,
        "source": food_log.source,
        "description": food_log.description,
        "calories": food_log.calories,
        "protein_g": rounded_metric(float(food_log.protein_g)),
        "carbs_g": rounded_metric(float(food_log.carbs_g)) if food_log.carbs_g is not None else None,
        "fat_g": rounded_metric(float(food_log.fat_g)) if food_log.fat_g is not None else None,
        "confidence": food_log.confidence,
        "telegram_metadata": food_log.telegram_metadata,
        "notes": food_log.notes,
        "items": [food_log_item_to_dict(item) for item in food_log.items],
        "created_at": food_log.created_at,
        "updated_at": food_log.updated_at,
    }


def food_log_item_to_dict(item: FoodLogItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "quantity": rounded_metric(float(item.quantity)) if item.quantity is not None else None,
        "unit": item.unit,
        "calories": item.calories,
        "protein_g": rounded_metric(float(item.protein_g)) if item.protein_g is not None else None,
        "carbs_g": rounded_metric(float(item.carbs_g)) if item.carbs_g is not None else None,
        "fat_g": rounded_metric(float(item.fat_g)) if item.fat_g is not None else None,
        "confidence": item.confidence,
        "notes": item.notes,
    }


def food_daily_review_to_dict(review: FoodDailyReview) -> dict[str, Any]:
    return {
        "id": review.id,
        "review_date": review.review_date,
        "hunger": review.hunger,
        "energy": review.energy,
        "adherence_status": review.adherence_status,
        "notes": review.notes,
        "recommendations": review.recommendations,
        "created_at": review.created_at,
        "updated_at": review.updated_at,
    }
