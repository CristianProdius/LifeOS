from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from lifeos_api.api.deps import get_session
from lifeos_api.domain.daily import create_daily_plan as create_daily_plan_service
from lifeos_api.schemas import DailyPlanRequest

router = APIRouter()


@router.post("/daily/plan", status_code=status.HTTP_201_CREATED)
def create_daily_plan(payload: DailyPlanRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    return create_daily_plan_service(session, payload)
