from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from lifeos_api.api.deps import get_session
from lifeos_api.domain.daily import build_daily_command_center
from lifeos_api.domain.daily import create_daily_plan as create_daily_plan_service
from lifeos_api.schemas import DailyCommandCenterRequest, DailyPlanRequest

router = APIRouter()


@router.post("/daily/plan", status_code=status.HTTP_201_CREATED)
def create_daily_plan(payload: DailyPlanRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    return create_daily_plan_service(session, payload)


@router.post("/daily/command-center", status_code=status.HTTP_201_CREATED)
def create_daily_command_center(
    payload: DailyCommandCenterRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    output, created = build_daily_command_center(session, payload)
    if not created:
        response.status_code = status.HTTP_200_OK
    return output
