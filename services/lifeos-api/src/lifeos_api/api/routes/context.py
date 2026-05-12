from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifeos_api.api.deps import get_session
from lifeos_api.core.time import lifeos_today
from lifeos_api.domain.food import (
    build_food_daily_summary,
    build_food_progress_context,
    get_or_create_active_food_target,
)
from lifeos_api.domain.health import build_health_progress
from lifeos_api.domain.profile import context_personalization, get_or_create_life_profile, profile_settings
from lifeos_api.models import Area, Checkin, HabitDefinition, HealthDailySummary, PlannedWorkout, Task, WorkoutSession
from lifeos_api.seed import get_or_create_user
from lifeos_api.serializers import (
    area_to_dict,
    checkin_to_dict,
    food_target_to_dict,
    habit_to_dict,
    health_daily_summary_to_dict,
    planned_workout_to_dict,
    profile_to_dict,
    task_to_dict,
    workout_to_dict,
)
from lifeos_api.utils import slugify

router = APIRouter()


@router.get("/context/{area_slug}")
def get_context(area_slug: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    user, _ = get_or_create_user(session)
    normalized_area_slug = slugify(area_slug)
    area = session.scalar(select(Area).where(Area.user_id == user.id, Area.slug == normalized_area_slug))
    if area is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="area not found")

    tasks = session.scalars(
        select(Task)
        .where(Task.user_id == user.id, Task.area_id == area.id)
        .order_by(Task.priority.desc(), Task.created_at.desc())
    ).all()
    habits = session.scalars(
        select(HabitDefinition)
        .where(
            HabitDefinition.user_id == user.id,
            HabitDefinition.area_id == area.id,
            HabitDefinition.is_active.is_(True),
        )
        .order_by(HabitDefinition.name)
    ).all()
    checkins = session.scalars(
        select(Checkin)
        .where(Checkin.user_id == user.id, Checkin.area_id == area.id)
        .order_by(Checkin.created_at.desc())
        .limit(5)
    ).all()

    context = {
        "area": area_to_dict(area),
        "tasks": [task_to_dict(task) for task in tasks],
        "habits": [habit_to_dict(habit) for habit in habits],
        "recent_checkins": [checkin_to_dict(checkin) for checkin in checkins],
    }
    if normalized_area_slug in {"sport", "daily", "food", "health"}:
        health_summaries = session.scalars(
            select(HealthDailySummary)
            .where(HealthDailySummary.user_id == user.id)
            .order_by(HealthDailySummary.summary_date.desc(), HealthDailySummary.updated_at.desc())
            .limit(7)
        ).all()
        settings = profile_settings(session, user.id)
        context["profile"] = profile_to_dict(get_or_create_life_profile(session, user.id))
        context["personalization"] = context_personalization(normalized_area_slug, settings)
        context["recent_health_summaries"] = [health_daily_summary_to_dict(summary) for summary in health_summaries]
        context["health_progress"] = build_health_progress(health_summaries)
    if normalized_area_slug == "food":
        target = get_or_create_active_food_target(session, user.id)
        today = lifeos_today()
        context["food_target"] = food_target_to_dict(target)
        context["today_food_summary"] = build_food_daily_summary(session, user.id, today, target)
        context["food_progress"] = build_food_progress_context(session, user.id, today, target)
        session.commit()
    if normalized_area_slug == "sport":
        active_plan = session.scalar(
            select(PlannedWorkout)
            .where(
                PlannedWorkout.user_id == user.id,
                PlannedWorkout.status.in_(["proposed", "accepted", "started"]),
            )
            .order_by(PlannedWorkout.plan_date.desc(), PlannedWorkout.created_at.desc())
        )
        latest_workout = session.scalar(
            select(WorkoutSession)
            .where(WorkoutSession.user_id == user.id)
            .order_by(WorkoutSession.session_date.desc(), WorkoutSession.created_at.desc())
        )
        context["active_planned_workout"] = planned_workout_to_dict(active_plan) if active_plan else None
        context["latest_workout"] = workout_to_dict(latest_workout) if latest_workout else None
    return context
