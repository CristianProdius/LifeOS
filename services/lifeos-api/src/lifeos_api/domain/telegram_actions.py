from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from lifeos_api.core.time import lifeos_today
from lifeos_api.domain.food import FoodLogNotFoundError, get_food_log_or_404
from lifeos_api.domain.workouts import (
    PlannedWorkoutNotFoundError,
    complete_planned_workout,
    get_planned_workout_or_404,
)
from lifeos_api.models import FoodLog, HabitDefinition, HabitLog, Task, utc_now
from lifeos_api.serializers import food_log_to_dict, habit_log_to_dict, planned_workout_to_dict, task_to_dict
from lifeos_api.utils import jsonable_data


class InvalidCallbackDataError(ValueError):
    """Raised when Telegram callback data does not match LifeOS action format."""


class UnsupportedTelegramActionError(ValueError):
    """Raised when a syntactically valid callback is outside this endpoint slice."""


class TelegramResourceNotFoundError(LookupError):
    """Raised when the callback references a missing LifeOS resource."""


@dataclass(frozen=True)
class TelegramCallback:
    kind: str
    resource_id: int
    action: str


def parse_callback_data(callback_data: str) -> TelegramCallback:
    parts = callback_data.split(":")
    if len(parts) == 4 and parts[0] == "lifeos" and parts[1] and parts[2] and parts[3]:
        try:
            resource_id = int(parts[2])
        except ValueError as exc:
            raise InvalidCallbackDataError(callback_data) from exc
        return TelegramCallback(kind=parts[1], resource_id=resource_id, action=parts[3])
    if len(parts) == 3 and parts[0] and parts[1] and parts[2]:
        try:
            resource_id = int(parts[2])
        except ValueError as exc:
            raise InvalidCallbackDataError(callback_data) from exc
        return TelegramCallback(kind=parts[0], resource_id=resource_id, action=parts[1])
    raise InvalidCallbackDataError(callback_data)


def apply_telegram_action(
    session: Session,
    user_id: int,
    *,
    callback_data: str,
    action_date: date | None,
    value: int | float | str | None,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    callback = parse_callback_data(callback_data)
    effective_date = action_date or lifeos_today()
    if callback.kind == "food":
        return apply_food_action(session, user_id, callback.resource_id, callback.action, value, metadata)
    if callback.kind == "workout":
        return apply_workout_action(session, user_id, callback.resource_id, callback.action)
    if callback.kind == "task":
        return apply_task_action(session, user_id, callback.resource_id, callback.action, effective_date)
    if callback.kind == "habit":
        return apply_habit_action(session, user_id, callback.resource_id, callback.action, effective_date)
    raise UnsupportedTelegramActionError(callback_data)


def apply_food_action(
    session: Session,
    user_id: int,
    food_log_id: int,
    action: str,
    value: int | float | str | None,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    try:
        food_log = get_food_log_or_404(session, user_id, food_log_id)
    except FoodLogNotFoundError as exc:
        raise TelegramResourceNotFoundError("food log not found") from exc

    if action == "looks_right":
        if food_log.confidence == "confirmed_estimate":
            return already_applied_response(food_log_to_dict(food_log), "Already confirmed.")
        food_log.confidence = "confirmed_estimate"
        merge_food_metadata(food_log, metadata)
        return saved_response(food_log_to_dict(food_log), "Confirmed.")
    if action == "edit_calories":
        numeric_value = numeric_action_value(value)
        if numeric_value is None:
            return food_needs_input_response(food_log, metadata, "calories")
        calories = int(round(numeric_value))
        if food_log.calories == calories:
            return already_applied_response(food_log_to_dict(food_log), "Calories already match.")
        food_log.calories = calories
        merge_food_metadata(food_log, metadata)
        return saved_response(food_log_to_dict(food_log), "Calories updated.")
    if action == "add_protein":
        numeric_value = numeric_action_value(value)
        if numeric_value is None:
            return food_needs_input_response(food_log, metadata, "protein_g")
        if food_log.protein_g == float(numeric_value):
            return already_applied_response(food_log_to_dict(food_log), "Protein already matches.")
        food_log.protein_g = float(numeric_value)
        merge_food_metadata(food_log, metadata)
        return saved_response(food_log_to_dict(food_log), "Protein updated.")
    if action == "delete":
        if food_log.status == "deleted":
            return already_applied_response(food_log_to_dict(food_log), "Already deleted.")
        food_log.status = "deleted"
        merge_food_metadata(food_log, metadata)
        return {
            "status": "deleted",
            "requires_input": False,
            "suppress_visible_reply": False,
            "acknowledgement": "Deleted.",
            "resource": food_log_to_dict(food_log),
        }
    raise UnsupportedTelegramActionError(action)


def food_needs_input_response(
    food_log: FoodLog,
    metadata: dict[str, Any],
    pending_correction: str,
) -> dict[str, Any]:
    merge_food_metadata(food_log, {**metadata, "pending_correction": pending_correction})
    return {
        "status": "needs_input",
        "requires_input": True,
        "suppress_visible_reply": False,
        "acknowledgement": "Send the corrected value.",
        "resource": food_log_to_dict(food_log),
    }


def merge_food_metadata(food_log: FoodLog, metadata: dict[str, Any]) -> None:
    merged = {**(food_log.telegram_metadata or {}), **jsonable_data(metadata)}
    food_log.telegram_metadata = merged


def numeric_action_value(value: int | float | str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def apply_workout_action(
    session: Session,
    user_id: int,
    plan_id: int,
    action: str,
) -> dict[str, Any]:
    try:
        plan = get_planned_workout_or_404(session, user_id, plan_id)
    except PlannedWorkoutNotFoundError as exc:
        raise TelegramResourceNotFoundError("planned workout not found") from exc

    if action == "start":
        if plan.status == "started":
            return already_applied_response(planned_workout_to_dict(plan), "Workout already started.")
        plan.status = "started"
        return saved_response(planned_workout_to_dict(plan), "Workout started.")
    if action == "done":
        if plan.status == "completed" and plan.completed_workout_id is not None:
            return already_applied_response(planned_workout_to_dict(plan), "Workout already completed.")
        complete_planned_workout(session, user_id, plan)
        return saved_response(planned_workout_to_dict(plan), "Workout completed.")
    if action == "too_hard":
        if plan.status == "replaced" and "too_hard" in (plan.notes or ""):
            return already_applied_response(planned_workout_to_dict(plan), "Workout already marked too hard.")
        plan.status = "replaced"
        plan.notes = notes_with_marker(plan.notes, "too_hard")
        return saved_response(planned_workout_to_dict(plan), "Marked too hard.")
    if action == "skip":
        if plan.status == "skipped":
            return already_applied_response(planned_workout_to_dict(plan), "Workout already skipped.")
        plan.status = "skipped"
        return saved_response(planned_workout_to_dict(plan), "Workout skipped.")
    if action == "change":
        return {
            "status": "needs_input",
            "requires_input": True,
            "suppress_visible_reply": False,
            "acknowledgement": "Ask what to change.",
            "resource": planned_workout_to_dict(plan),
        }
    raise UnsupportedTelegramActionError(action)


def apply_task_action(
    session: Session,
    user_id: int,
    task_id: int,
    action: str,
    action_date: date,
) -> dict[str, Any]:
    task = session.scalar(select(Task).where(Task.id == task_id, Task.user_id == user_id))
    if task is None:
        raise TelegramResourceNotFoundError("task not found")
    if action == "done":
        if task.status == "done" and task.completed_at is not None:
            return already_applied_response(task_to_dict(task), "Task already done.")
        task.status = "done"
        task.completed_at = utc_now()
        return saved_response(task_to_dict(task), "Task done.")
    if action == "block":
        if task.status == "blocked":
            return already_applied_response(task_to_dict(task), "Task already blocked.")
        task.status = "blocked"
        task.completed_at = None
        return saved_response(task_to_dict(task), "Task blocked.")
    if action == "snooze_tomorrow":
        tomorrow = action_date + timedelta(days=1)
        if task.status == "todo" and task.due_date == tomorrow and task.completed_at is None:
            return already_applied_response(task_to_dict(task), "Task already snoozed.")
        task.status = "todo"
        task.completed_at = None
        task.due_date = tomorrow
        return saved_response(task_to_dict(task), "Task snoozed to tomorrow.")
    raise UnsupportedTelegramActionError(action)


def apply_habit_action(
    session: Session,
    user_id: int,
    habit_id: int,
    action: str,
    action_date: date,
) -> dict[str, Any]:
    habit = session.scalar(select(HabitDefinition).where(HabitDefinition.id == habit_id, HabitDefinition.user_id == user_id))
    if habit is None:
        raise TelegramResourceNotFoundError("habit not found")
    log = session.scalar(select(HabitLog).where(HabitLog.habit_id == habit.id, HabitLog.log_date == action_date))
    if log is None:
        log = HabitLog(user_id=user_id, habit_id=habit.id, log_date=action_date)
        session.add(log)
        session.flush()
    log.habit = habit
    if action == "done":
        if log.value == 1:
            return already_applied_response(habit_log_to_dict(log), "Habit already marked done.")
        log.value = 1
        return saved_response(habit_log_to_dict(log), "Habit done.")
    if action == "missed":
        if log.value == 0 and "skipped" not in (log.notes or ""):
            return already_applied_response(habit_log_to_dict(log), "Habit already marked missed.")
        log.value = 0
        return saved_response(habit_log_to_dict(log), "Habit marked missed.")
    if action == "skip":
        if log.value == 0 and "skipped" in (log.notes or ""):
            return already_applied_response(habit_log_to_dict(log), "Habit already skipped.")
        log.value = 0
        log.notes = notes_with_marker(log.notes, "skipped")
        return saved_response(habit_log_to_dict(log), "Habit skipped.")
    raise UnsupportedTelegramActionError(action)


def notes_with_marker(notes: str | None, marker: str) -> str:
    if not notes:
        return marker
    if marker in notes:
        return notes
    return f"{notes}\n{marker}"


def saved_response(resource: dict[str, Any], acknowledgement: str) -> dict[str, Any]:
    return {
        "status": "saved",
        "requires_input": False,
        "suppress_visible_reply": False,
        "acknowledgement": acknowledgement,
        "resource": resource,
    }


def already_applied_response(resource: dict[str, Any], acknowledgement: str) -> dict[str, Any]:
    return {
        "status": "already_applied",
        "requires_input": False,
        "suppress_visible_reply": True,
        "acknowledgement": acknowledgement,
        "resource": resource,
    }
