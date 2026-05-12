from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from lifeos_api.api.deps import get_session
from lifeos_api.domain.daily import build_daily_recommendations
from lifeos_api.models import AdviceLog, DailyPlan, HabitDefinition, Task
from lifeos_api.schemas import DailyPlanRequest
from lifeos_api.seed import ensure_area, get_or_create_user
from lifeos_api.serializers import daily_plan_to_dict, habit_to_dict, task_to_dict

router = APIRouter()


@router.post("/daily/plan", status_code=status.HTTP_201_CREATED)
def create_daily_plan(payload: DailyPlanRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
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

    task_payload = jsonable_encoder([task_to_dict(task) for task in tasks])
    habit_payload = jsonable_encoder([habit_to_dict(habit) for habit in habits])
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
            output_payload=jsonable_encoder(output),
        )
    )
    session.commit()
    session.refresh(plan)
    return output
