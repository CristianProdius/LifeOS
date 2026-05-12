from __future__ import annotations

from typing import Any

from lifeos_api.models import Area, Checkin, HabitDefinition, HabitLog, Task


def area_to_dict(area: Area) -> dict[str, Any]:
    return {"id": area.id, "slug": area.slug, "name": area.name, "description": area.description}


def task_to_dict(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "title": task.title,
        "area": task.area.slug if task.area else None,
        "status": task.status,
        "priority": task.priority,
        "due_date": task.due_date,
        "notes": task.notes,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def habit_to_dict(habit: HabitDefinition) -> dict[str, Any]:
    return {
        "id": habit.id,
        "slug": habit.slug,
        "name": habit.name,
        "target_value": habit.target_value,
        "unit": habit.unit,
        "frequency": habit.frequency,
    }


def habit_log_to_dict(log: HabitLog) -> dict[str, Any]:
    return {
        "id": log.id,
        "habit": log.habit.slug,
        "log_date": log.log_date,
        "value": log.value,
        "notes": log.notes,
    }


def checkin_to_dict(checkin: Checkin) -> dict[str, Any]:
    return {
        "id": checkin.id,
        "area": checkin.area.slug if checkin.area else None,
        "mood": checkin.mood,
        "energy": checkin.energy,
        "stress": checkin.stress,
        "notes": checkin.notes,
        "created_at": checkin.created_at,
    }
