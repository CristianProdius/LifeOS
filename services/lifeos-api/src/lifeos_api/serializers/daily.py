from __future__ import annotations

from typing import Any

from lifeos_api.models import DailyPlan, DailyReview, WeeklyReview


def daily_plan_to_dict(plan: DailyPlan, focus_area: str | None) -> dict[str, Any]:
    return {
        "id": plan.id,
        "plan_date": plan.plan_date,
        "focus_area": focus_area,
        "capacity_minutes": plan.capacity_minutes,
        "tasks": plan.tasks,
        "habits": plan.habits,
        "recommendations": plan.recommendations,
    }


def daily_review_to_dict(review: DailyReview) -> dict[str, Any]:
    return {
        "id": review.id,
        "review_date": review.review_date,
        "wins": review.wins,
        "blockers": review.blockers,
        "mood": review.mood,
        "energy": review.energy,
        "notes": review.notes,
    }


def weekly_review_to_dict(review: WeeklyReview) -> dict[str, Any]:
    return {
        "id": review.id,
        "week_start": review.week_start,
        "wins": review.wins,
        "lessons": review.lessons,
        "next_focus": review.next_focus,
        "score": review.score,
        "notes": review.notes,
    }
