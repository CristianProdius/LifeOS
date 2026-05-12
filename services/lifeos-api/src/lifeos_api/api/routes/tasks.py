from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifeos_api.api.deps import get_session
from lifeos_api.models import Task, utc_now
from lifeos_api.schemas import TaskCreate, TaskUpdate
from lifeos_api.seed import ensure_area, get_or_create_user
from lifeos_api.serializers import task_to_dict

router = APIRouter()


@router.post("/tasks", status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate, session: Session = Depends(get_session)) -> dict[str, Any]:
    user, _ = get_or_create_user(session)
    area = ensure_area(session, user.id, payload.area)
    task = Task(
        user_id=user.id,
        area_id=area.id,
        title=payload.title,
        notes=payload.notes,
        priority=payload.priority,
        due_date=payload.due_date,
        status="todo",
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    task.area = area
    return task_to_dict(task)


@router.patch("/tasks/{task_id}")
def update_task(task_id: int, payload: TaskUpdate, session: Session = Depends(get_session)) -> dict[str, Any]:
    user, _ = get_or_create_user(session)
    task = session.scalar(select(Task).where(Task.id == task_id, Task.user_id == user.id))
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")

    updates = payload.model_dump(exclude_unset=True)
    if "area" in updates and updates["area"] is not None:
        area = ensure_area(session, user.id, updates.pop("area"))
        task.area_id = area.id
        task.area = area
    for field, value in updates.items():
        setattr(task, field, value)
    if "status" in updates:
        task.completed_at = utc_now() if updates["status"] == "done" else None

    session.commit()
    session.refresh(task)
    return task_to_dict(task)
