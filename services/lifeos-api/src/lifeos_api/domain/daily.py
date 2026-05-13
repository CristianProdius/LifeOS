from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from lifeos_api.models import AdviceLog, Area, DailyPlan, HabitDefinition, HealthDailySummary, Task
from lifeos_api.schemas import DailyCommandCenterRequest, DailyPlanRequest
from lifeos_api.seed import ensure_area, get_or_create_user
from lifeos_api.serializers import daily_plan_to_dict, habit_to_dict, task_to_dict
from lifeos_api.utils import jsonable_data


COMMAND_CENTER_SLOT_KEY = "command_center_slot"
COMMAND_CENTER_SLOTS = ("health", "business", "anti_distraction", "admin_review")


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


def _task_buttons(task_id: int) -> list[dict[str, str]]:
    return [
        {"label": "Done", "value": f"lifeos:task:{task_id}:done"},
        {"label": "Block", "value": f"lifeos:task:{task_id}:block"},
        {"label": "Snooze tomorrow", "value": f"lifeos:task:{task_id}:snooze_tomorrow"},
    ]


def _find_or_create_task(
    session: Session,
    user_id: int,
    area: Area,
    *,
    title: str,
    due_date: date,
    priority: int,
    notes: str,
) -> Task:
    fallback_task = session.scalar(
        select(Task).where(
            Task.user_id == user_id,
            Task.area_id == area.id,
            Task.title == title,
            Task.due_date == due_date,
            Task.status != "done",
        )
    )
    if fallback_task is not None:
        fallback_task.area = area
        return fallback_task

    existing_task = find_due_slot_task(session, user_id, area, due_date)
    if existing_task is not None:
        existing_task.area = area
        return existing_task

    task = Task(
        user_id=user_id,
        area_id=area.id,
        title=title,
        notes=notes,
        status="todo",
        priority=priority,
        due_date=due_date,
    )
    task.area = area
    session.add(task)
    session.flush()
    return task


def find_due_slot_task(session: Session, user_id: int, area: Area, plan_date: date) -> Task | None:
    task = session.scalar(
        select(Task)
        .where(
            Task.user_id == user_id,
            Task.area_id == area.id,
            Task.status != "done",
            Task.due_date.is_not(None),
            Task.due_date <= plan_date,
        )
        .order_by(Task.priority.desc(), Task.due_date.asc(), Task.created_at.asc())
    )
    if task is not None:
        task.area = area
    return task


def _business_commitment_task(session: Session, user_id: int, area: Area, plan_date: date) -> Task:
    task = find_due_slot_task(session, user_id, area, plan_date)
    if task is not None:
        return task

    return _find_or_create_task(
        session,
        user_id,
        area,
        title="Ship one business outcome",
        due_date=plan_date,
        priority=5,
        notes="Conservative fallback when no due business task exists for the command center.",
    )


def _task_by_id(session: Session, user_id: int, task_id: int) -> Task | None:
    return session.scalar(
        select(Task).where(
            Task.user_id == user_id,
            Task.id == task_id,
        )
    )


def _commitment_from_task(slot: str, task: Task) -> dict[str, Any]:
    task_payload = jsonable_data(task_to_dict(task))
    return {
        "slot": slot,
        "task": task_payload,
        "title": task.title,
        "area": task_payload["area"],
        "due_date": task_payload["due_date"],
        "buttons": _task_buttons(task.id),
    }


def _commitments_from_snapshot(
    session: Session,
    user_id: int,
    snapshot: list[dict[str, Any]],
) -> list[dict[str, Any]] | None:
    if len(snapshot) != len(COMMAND_CENTER_SLOTS):
        return None
    commitments = []
    for slot, task_payload in zip(COMMAND_CENTER_SLOTS, snapshot, strict=True):
        if task_payload.get(COMMAND_CENTER_SLOT_KEY) != slot:
            return None
        task_id = task_payload.get("id")
        if not isinstance(task_id, int):
            return None
        task = _task_by_id(session, user_id, task_id)
        if task is None:
            return None
        commitments.append(_commitment_from_task(slot, task))
    return commitments


def _scorecard(commitments: list[dict[str, Any]]) -> dict[str, int]:
    completed = sum(1 for commitment in commitments if commitment["task"]["status"] == "done")
    return {"total": len(commitments), "completed": completed}


def _stored_commitment_task(commitment: dict[str, Any]) -> dict[str, Any]:
    task = dict(commitment["task"])
    task[COMMAND_CENTER_SLOT_KEY] = commitment["slot"]
    return task


def _command_center_commitments(session: Session, user_id: int, plan_date: date) -> list[dict[str, Any]]:
    health_area = ensure_area(session, user_id, "health")
    business_area = ensure_area(session, user_id, "business")
    daily_area = ensure_area(session, user_id, "daily")
    admin_area = ensure_area(session, user_id, "admin")

    slot_tasks = {
        "health": _find_or_create_task(
            session,
            user_id,
            health_area,
            title="Sync health basics",
            due_date=plan_date,
            priority=4,
            notes="Weigh in, sync activity, and check recovery signal.",
        ),
        "business": _business_commitment_task(session, user_id, business_area, plan_date),
        "anti_distraction": _find_or_create_task(
            session,
            user_id,
            daily_area,
            title="Protect one anti-distraction block",
            due_date=plan_date,
            priority=4,
            notes="One focused block before feeds, inboxes, or unplanned inputs.",
        ),
        "admin_review": _find_or_create_task(
            session,
            user_id,
            admin_area,
            title="Review admin queue and daily plan",
            due_date=plan_date,
            priority=3,
            notes="Check open operational items and update the end-of-day review path.",
        ),
    }

    commitments = []
    for slot in COMMAND_CENTER_SLOTS:
        task = slot_tasks[slot]
        commitments.append(_commitment_from_task(slot, task))
    return commitments


def _health_sync(session: Session, user_id: int, plan_date: date) -> dict[str, Any]:
    summary = session.scalar(
        select(HealthDailySummary)
        .where(
            HealthDailySummary.user_id == user_id,
            HealthDailySummary.summary_date.in_([plan_date, plan_date - timedelta(days=1)]),
        )
        .order_by(HealthDailySummary.summary_date.desc(), HealthDailySummary.updated_at.desc())
    )
    return {
        "synced": summary is not None,
        "summary_date": summary.summary_date if summary else None,
        "source": summary.source if summary else None,
    }


def build_daily_command_center(
    session: Session,
    payload: DailyCommandCenterRequest,
) -> tuple[dict[str, Any], bool]:
    user, _ = get_or_create_user(session)
    plan = session.scalar(
        select(DailyPlan).where(DailyPlan.user_id == user.id, DailyPlan.plan_date == payload.plan_date)
    )
    created = plan is None
    if plan is None:
        plan = DailyPlan(user_id=user.id, plan_date=payload.plan_date)
        session.add(plan)
        session.flush()

    commitments = _commitments_from_snapshot(session, user.id, list(plan.tasks or []))
    if commitments is None:
        commitments = _command_center_commitments(session, user.id, payload.plan_date)
    plan.capacity_minutes = payload.capacity_minutes
    plan.tasks = jsonable_data([_stored_commitment_task(commitment) for commitment in commitments])
    plan.habits = []
    plan.recommendations = [
        "Complete the four command-center commitments before expanding the day.",
        "Escalate blockers from the buttons instead of letting them sit in memory.",
    ]

    session.flush()
    daily_plan = daily_plan_to_dict(plan, None)
    output = {
        "plan_date": payload.plan_date,
        "daily_plan": jsonable_data(daily_plan),
        "mandatory_commitments": commitments,
        "scorecard": _scorecard(commitments),
        "health_sync": jsonable_data(_health_sync(session, user.id, payload.plan_date)),
    }
    session.add(
        AdviceLog(
            user_id=user.id,
            advice_type="daily_command_center",
            input_payload=payload.model_dump(mode="json"),
            output_payload=jsonable_data(output),
        )
    )
    session.commit()
    session.refresh(plan)
    output["daily_plan"] = jsonable_data(daily_plan_to_dict(plan, None))
    return output, created
