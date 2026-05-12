from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifeos_api.api.deps import get_session
from lifeos_api.models import HabitDefinition, HabitLog
from lifeos_api.schemas import HabitLogCreate
from lifeos_api.seed import get_or_create_user
from lifeos_api.serializers import habit_log_to_dict
from lifeos_api.utils import slugify

router = APIRouter()


@router.post("/habits/log", status_code=status.HTTP_201_CREATED)
def log_habit(
    payload: HabitLogCreate,
    response: Response,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    user, _ = get_or_create_user(session)
    habit_slug = slugify(payload.habit)
    habit = session.scalar(
        select(HabitDefinition).where(HabitDefinition.user_id == user.id, HabitDefinition.slug == habit_slug)
    )
    if habit is None:
        habit = HabitDefinition(user_id=user.id, slug=habit_slug, name=payload.habit.strip().title())
        session.add(habit)
        session.flush()

    log = session.scalar(select(HabitLog).where(HabitLog.habit_id == habit.id, HabitLog.log_date == payload.log_date))
    created = log is None
    if log is None:
        log = HabitLog(user_id=user.id, habit_id=habit.id, log_date=payload.log_date)
        session.add(log)
    log.value = payload.value
    log.notes = payload.notes
    session.commit()
    session.refresh(log)
    log.habit = habit
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return habit_log_to_dict(log)
