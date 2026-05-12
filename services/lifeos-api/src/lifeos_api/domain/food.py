from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from lifeos_api.core.time import lifeos_today
from lifeos_api.models import FoodLog, FoodLogItem, FoodTarget, HealthDailySummary
from lifeos_api.schemas import FoodLogItemPayload
from lifeos_api.serializers import food_log_to_dict, food_target_to_dict
from lifeos_api.utils import rounded_metric

FOOD_LOG_STATUSES = {"active", "deleted"}
FOOD_DEFAULT_AGE_YEARS = 23
FOOD_DEFAULT_HEIGHT_CM = 175
FOOD_DEFAULT_SEX = "male"
FOOD_DEFAULT_WEIGHT_KG = 117.0
FOOD_DEFAULT_ACTIVITY_FACTOR = 1.25
FOOD_DEFAULT_CALORIES = 1900
FOOD_DEFAULT_PROTEIN_G = 150.0
FOOD_DEFAULT_FAT_G = 60.0
FOOD_CALORIE_FLOOR = 1800


class FoodLogNotFoundError(LookupError):
    """Raised when a food log cannot be found for a user."""


def get_or_create_active_food_target(
    session: Session,
    user_id: int,
    effective_date: date | None = None,
) -> FoodTarget:
    effective_date = effective_date or lifeos_today()
    target = session.scalar(
        select(FoodTarget)
        .where(
            FoodTarget.user_id == user_id,
            FoodTarget.status == "active",
            FoodTarget.start_date <= effective_date,
            or_(FoodTarget.end_date.is_(None), FoodTarget.end_date >= effective_date),
        )
        .order_by(FoodTarget.start_date.desc(), FoodTarget.created_at.desc())
        .limit(1)
    )
    if target is not None:
        return target
    return create_food_target(session, user_id, effective_date)


def create_food_target(
    session: Session,
    user_id: int,
    effective_date: date,
    *,
    calories_override: int | None = None,
    protein_override: float | None = None,
    notes: str | None = None,
    archive_existing: bool = False,
) -> FoodTarget:
    if archive_existing:
        active_targets = session.scalars(
            select(FoodTarget).where(FoodTarget.user_id == user_id, FoodTarget.status == "active")
        ).all()
        for active_target in active_targets:
            active_target.status = "archived"
            active_target.end_date = min(effective_date, active_target.start_date) if active_target.start_date >= effective_date else effective_date - timedelta(days=1)

    calculation = build_food_target_calculation(session, user_id, calories_override, protein_override)
    target = FoodTarget(
        user_id=user_id,
        start_date=effective_date,
        status="active",
        calories=calculation["target"]["calories"],
        protein_g=calculation["target"]["protein_g"],
        carbs_g=calculation["target"]["carbs_g"],
        fat_g=calculation["target"]["fat_g"],
        calorie_floor=FOOD_CALORIE_FLOOR,
        source="manual_override" if calories_override is not None or protein_override is not None else "calculated",
        calculation=calculation,
        notes=notes,
    )
    session.add(target)
    session.flush()
    return target


def build_food_target_calculation(
    session: Session,
    user_id: int,
    calories_override: int | None = None,
    protein_override: float | None = None,
) -> dict[str, Any]:
    latest_weight = latest_food_weight_kg(session, user_id)
    weight_kg = float(latest_weight if latest_weight is not None else FOOD_DEFAULT_WEIGHT_KG)
    bmr_exact = (10 * weight_kg) + (6.25 * FOOD_DEFAULT_HEIGHT_CM) - (5 * FOOD_DEFAULT_AGE_YEARS) + 5
    estimated_tdee = int(round(bmr_exact * FOOD_DEFAULT_ACTIVITY_FACTOR))
    calories = int(calories_override or FOOD_DEFAULT_CALORIES)
    calories = max(calories, FOOD_CALORIE_FLOOR)
    protein_g = float(protein_override or FOOD_DEFAULT_PROTEIN_G)
    fat_g = FOOD_DEFAULT_FAT_G
    carbs_g = max((calories - (protein_g * 4) - (fat_g * 9)) / 4, 0)
    return {
        "formula": "mifflin_st_jeor",
        "inputs": {
            "sex": FOOD_DEFAULT_SEX,
            "age_years": FOOD_DEFAULT_AGE_YEARS,
            "height_cm": FOOD_DEFAULT_HEIGHT_CM,
            "weight_kg": rounded_metric(weight_kg),
            "activity_factor": FOOD_DEFAULT_ACTIVITY_FACTOR,
        },
        "bmr_kcal": int(round(bmr_exact)),
        "estimated_tdee_kcal": estimated_tdee,
        "strategy": "aggressive_adjustable_cut",
        "target": {
            "calories": calories,
            "protein_g": rounded_metric(protein_g),
            "carbs_g": rounded_metric(carbs_g),
            "fat_g": rounded_metric(fat_g),
            "calorie_floor": FOOD_CALORIE_FLOOR,
        },
        "data_quality": {
            "used_latest_weight": latest_weight is not None,
            "target_is_coaching_estimate": True,
        },
    }


def latest_food_weight_kg(session: Session, user_id: int) -> float | None:
    value = session.scalar(
        select(HealthDailySummary.weight_kg)
        .where(HealthDailySummary.user_id == user_id, HealthDailySummary.weight_kg.is_not(None))
        .order_by(HealthDailySummary.summary_date.desc(), HealthDailySummary.updated_at.desc())
        .limit(1)
    )
    return float(value) if value is not None else None


def food_log_item_from_payload(payload: FoodLogItemPayload) -> FoodLogItem:
    return FoodLogItem(**payload.model_dump(exclude_none=True))


def get_food_log_or_404(session: Session, user_id: int, food_log_id: int) -> FoodLog:
    food_log = session.scalar(select(FoodLog).where(FoodLog.id == food_log_id, FoodLog.user_id == user_id))
    if food_log is None:
        raise FoodLogNotFoundError(food_log_id)
    return food_log


def build_food_daily_summary(
    session: Session,
    user_id: int,
    summary_date: date,
    target: FoodTarget,
) -> dict[str, Any]:
    logs = session.scalars(
        select(FoodLog)
        .where(FoodLog.user_id == user_id, FoodLog.log_date == summary_date, FoodLog.status == "active")
        .order_by(FoodLog.created_at.asc(), FoodLog.id.asc())
    ).all()
    totals = food_totals(logs)
    remaining = {
        "calories": max(target.calories - totals["calories"], 0),
        "protein_g": rounded_metric(max(float(target.protein_g) - float(totals["protein_g"]), 0)),
    }
    return {
        "summary_date": summary_date,
        "target": food_target_to_dict(target),
        "totals": totals,
        "remaining": remaining,
        "adherence": build_food_adherence(totals, target, len(logs)),
        "logs": [food_log_to_dict(food_log) for food_log in logs],
        "data_quality": {
            "logged_meals": len(logs),
            "has_estimates": any(food_log.confidence != "exact" for food_log in logs),
            "missing_logs": len(logs) == 0,
            "missing_calories": any(food_log.calories is None for food_log in logs),
            "missing_protein": any(food_log.protein_g is None for food_log in logs),
        },
    }


def food_totals(logs: list[FoodLog]) -> dict[str, Any]:
    return {
        "calories": int(sum(food_log.calories or 0 for food_log in logs)),
        "protein_g": rounded_metric(sum(float(food_log.protein_g or 0) for food_log in logs)),
        "carbs_g": rounded_metric(sum(float(food_log.carbs_g or 0) for food_log in logs if food_log.carbs_g is not None)),
        "fat_g": rounded_metric(sum(float(food_log.fat_g or 0) for food_log in logs if food_log.fat_g is not None)),
    }


def build_food_adherence(totals: dict[str, Any], target: FoodTarget, logged_meals: int) -> dict[str, Any]:
    if logged_meals == 0:
        calorie_status = "no_logs"
    elif totals["calories"] > target.calories:
        calorie_status = "over_target"
    elif totals["calories"] >= target.calories - 150:
        calorie_status = "near_target"
    else:
        calorie_status = "under_target"
    protein_status = "hit" if float(totals["protein_g"]) >= float(target.protein_g) else "short"
    return {
        "calorie_status": calorie_status,
        "protein_status": protein_status,
        "calorie_delta": int(totals["calories"] - target.calories),
        "protein_delta_g": rounded_metric(float(totals["protein_g"]) - float(target.protein_g)),
    }


def build_food_progress_context(
    session: Session,
    user_id: int,
    reference_date: date,
    target: FoodTarget,
) -> dict[str, Any]:
    window_start = reference_date - timedelta(days=6)
    logs = session.scalars(
        select(FoodLog)
        .where(
            FoodLog.user_id == user_id,
            FoodLog.status == "active",
            FoodLog.log_date >= window_start,
            FoodLog.log_date <= reference_date,
        )
        .order_by(FoodLog.log_date.asc(), FoodLog.created_at.asc())
    ).all()
    logs_by_day: dict[date, list[FoodLog]] = {}
    for food_log in logs:
        logs_by_day.setdefault(food_log.log_date, []).append(food_log)

    day_rows = []
    for log_date, day_logs in sorted(logs_by_day.items()):
        totals = food_totals(day_logs)
        day_rows.append(
            {
                "date": log_date,
                "totals": totals,
                "adherence": build_food_adherence(totals, target, len(day_logs)),
                "logged_meals": len(day_logs),
            }
        )

    logged_days = len(day_rows)
    averages = {
        "calories": rounded_metric(sum(day["totals"]["calories"] for day in day_rows) / logged_days) if logged_days else 0,
        "protein_g": rounded_metric(sum(float(day["totals"]["protein_g"]) for day in day_rows) / logged_days) if logged_days else 0,
    }
    calorie_adherent_days = sum(1 for day in day_rows if day["totals"]["calories"] <= target.calories and day["totals"]["calories"] >= target.calories - 250)
    protein_adherent_days = sum(1 for day in day_rows if float(day["totals"]["protein_g"]) >= float(target.protein_g))
    weight_entries = food_weight_entries(session, user_id, window_start, reference_date)
    weight_trend = build_food_weight_trend(weight_entries)
    enough_data = logged_days >= 5 and len(weight_entries) >= 3
    adherence = {
        "calorie_adherence_rate": rounded_metric(calorie_adherent_days / logged_days) if logged_days else 0,
        "protein_adherence_rate": rounded_metric(protein_adherent_days / logged_days) if logged_days else 0,
    }
    return {
        "reference_date": reference_date,
        "window_start": window_start,
        "target": food_target_to_dict(target),
        "daily_summaries": day_rows,
        "averages": averages,
        "adherence": adherence,
        "weight_trend": weight_trend,
        "adjustment": build_food_adjustment(target, averages, adherence, weight_trend, enough_data),
        "data_quality": {
            "logged_food_days": logged_days,
            "weight_entries": len(weight_entries),
            "enough_data_for_adjustment": enough_data,
            "missing_food_days": max(7 - logged_days, 0),
            "trend_note": "Enough data for cautious adjustment." if enough_data else "Need at least 5 logged food days and 3 weight entries before adjusting.",
        },
    }


def food_weight_entries(session: Session, user_id: int, start_date: date, end_date: date) -> list[dict[str, Any]]:
    summaries = session.scalars(
        select(HealthDailySummary)
        .where(
            HealthDailySummary.user_id == user_id,
            HealthDailySummary.weight_kg.is_not(None),
            HealthDailySummary.summary_date >= start_date,
            HealthDailySummary.summary_date <= end_date,
        )
        .order_by(HealthDailySummary.summary_date.asc(), HealthDailySummary.updated_at.asc())
    ).all()
    by_date: dict[date, HealthDailySummary] = {}
    for summary in summaries:
        by_date[summary.summary_date] = summary
    return [
        {
            "date": summary.summary_date,
            "weight_kg": float(summary.weight_kg),
            "source": summary.source,
            "updated_at": summary.updated_at,
        }
        for summary in sorted(by_date.values(), key=lambda item: item.summary_date)
    ]


def build_food_weight_trend(weight_entries: list[dict[str, Any]]) -> dict[str, Any]:
    if not weight_entries:
        return {
            "latest_weight_kg": None,
            "delta_kg": None,
            "weekly_rate_kg": None,
            "status": "no_weight_data",
        }
    first = weight_entries[0]
    latest = weight_entries[-1]
    delta = float(latest["weight_kg"]) - float(first["weight_kg"])
    days = max((latest["date"] - first["date"]).days, 1)
    return {
        "start_date": first["date"],
        "latest_date": latest["date"],
        "start_weight_kg": rounded_metric(float(first["weight_kg"])),
        "latest_weight_kg": rounded_metric(float(latest["weight_kg"])),
        "delta_kg": rounded_metric(delta),
        "weekly_rate_kg": rounded_metric((delta / days) * 7),
        "status": "available" if len(weight_entries) >= 3 else "needs_more_data",
    }


def build_food_adjustment(
    target: FoodTarget,
    averages: dict[str, Any],
    adherence: dict[str, Any],
    weight_trend: dict[str, Any],
    enough_data: bool,
) -> dict[str, Any]:
    if not enough_data:
        return {
            "action": "no_adjustment_insufficient_data",
            "next_calories": target.calories,
            "reason": "Need at least 5 logged food days and 3 weight entries.",
        }
    weekly_rate = weight_trend.get("weekly_rate_kg")
    weekly_loss = -float(weekly_rate or 0)
    if weekly_loss < 0.35 and float(adherence["calorie_adherence_rate"]) >= 0.8:
        next_calories = max(target.calorie_floor, target.calories - 100)
        return {
            "action": "reduce_calories_by_100" if next_calories < target.calories else "hold_at_calorie_floor",
            "next_calories": next_calories,
            "reason": "Weight trend is slower than target while logged calories are close to plan.",
        }
    if weekly_loss > 1.2:
        return {
            "action": "increase_calories_by_100",
            "next_calories": target.calories + 100,
            "reason": "Weight trend is faster than the safe coaching band.",
        }
    return {
        "action": "hold_target",
        "next_calories": target.calories,
        "reason": "Recent weight and food adherence are inside the current adjustment band.",
    }
