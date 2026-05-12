from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from lifeos_api.models import AdviceLog, DailyPlan, HabitDefinition, Task
from lifeos_api.schemas import DailyPlanRequest
from lifeos_api.seed import ensure_area, get_or_create_user
from lifeos_api.serializers import daily_plan_to_dict, habit_to_dict, task_to_dict
from lifeos_api.utils import jsonable_data


def build_daily_recommendations(
    capacity_minutes: int,
    tasks: list[dict[str, Any]],
    habits: list[dict[str, Any]],
) -> list[str]:
    recommendations = []
    if tasks:
        recommendations.append("Start with the highest-priority task before checking new inputs.")
    if habits:
        recommendations.append("Log the smallest version of each habit before the day gets noisy.")
    if capacity_minutes < 60:
        recommendations.append("Keep the plan narrow and protect recovery time.")
    else:
        recommendations.append("Leave at least one unscheduled buffer block.")
    return recommendations


def create_daily_plan(session: Session, payload: DailyPlanRequest) -> dict[str, Any]:
    user, _ = get_or_create_user(session)
    focus_area = ensure_area(session, user.id, payload.focus_area) if payload.focus_area else None

    task_query = select(Task).where(Task.user_id == user.id, Task.status != "done")
    if focus_area is not None:
        task_query = task_query.where(Task.area_id == focus_area.id)
    else:
        task_query = task_query.where(or_(Task.due_date.is_(None), Task.due_date <= payload.plan_date))
    tasks = session.scalars(task_query.order_by(Task.priority.desc(), Task.created_at).limit(5)).all()

    habit_query = select(HabitDefinition).where(HabitDefinition.user_id == user.id, HabitDefinition.is_active.is_(True))
    if focus_area is not None:
        habit_query = habit_query.where(HabitDefinition.area_id == focus_area.id)
    habits = session.scalars(habit_query.order_by(HabitDefinition.name).limit(5)).all()

    task_payload = jsonable_data([task_to_dict(task) for task in tasks])
    habit_payload = jsonable_data([habit_to_dict(habit) for habit in habits])
    recommendations = build_daily_recommendations(payload.capacity_minutes, task_payload, habit_payload)

    plan = session.scalar(
        select(DailyPlan).where(DailyPlan.user_id == user.id, DailyPlan.plan_date == payload.plan_date)
    )
    if plan is None:
        plan = DailyPlan(user_id=user.id, plan_date=payload.plan_date)
        session.add(plan)
    plan.focus_area_id = focus_area.id if focus_area else None
    plan.capacity_minutes = payload.capacity_minutes
    plan.tasks = task_payload
    plan.habits = habit_payload
    plan.recommendations = recommendations

    session.flush()
    output = daily_plan_to_dict(plan, focus_area.slug if focus_area else None)
    session.add(
        AdviceLog(
            user_id=user.id,
            advice_type="daily_plan",
            input_payload=payload.model_dump(mode="json"),
            output_payload=jsonable_data(output),
        )
    )
    session.commit()
    session.refresh(plan)
    return output
