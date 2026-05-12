from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from lifeos_api.api.deps import get_session
from lifeos_api.models import Checkin
from lifeos_api.schemas import CheckinCreate
from lifeos_api.seed import ensure_area, get_or_create_user
from lifeos_api.serializers import checkin_to_dict

router = APIRouter()


@router.post("/checkins", status_code=status.HTTP_201_CREATED)
def create_checkin(payload: CheckinCreate, session: Session = Depends(get_session)) -> dict[str, Any]:
    user, _ = get_or_create_user(session)
    area = ensure_area(session, user.id, payload.area)
    checkin = Checkin(
        user_id=user.id,
        area_id=area.id,
        mood=payload.mood,
        energy=payload.energy,
        stress=payload.stress,
        notes=payload.notes,
    )
    session.add(checkin)
    session.commit()
    session.refresh(checkin)
    checkin.area = area
    return checkin_to_dict(checkin)
