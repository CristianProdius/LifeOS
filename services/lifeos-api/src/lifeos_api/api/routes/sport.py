from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from lifeos_api.api.deps import get_session
from lifeos_api.domain.profile import profile_settings
from lifeos_api.domain.sport import (
    SportProgramError,
    build_sport_progress,
    create_missed_day_adjustment,
    create_or_reuse_sport_today_workout,
    sport_program_context,
)
from lifeos_api.schemas import SportMissedDayRequest, SportTodayRequest
from lifeos_api.seed import get_or_create_user, seed_sport_program

router = APIRouter()


def sport_program_http_exception(exc: SportProgramError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=exc.detail)


@router.post("/sport/program/seed")
def seed_sport_program_endpoint(response: Response, session: Session = Depends(get_session)) -> dict[str, Any]:
    user, _ = get_or_create_user(session)
    result = seed_sport_program(session, user.id)
    response.status_code = status.HTTP_201_CREATED if result["created"] else status.HTTP_200_OK
    try:
        return sport_program_context(session, user.id)
    except SportProgramError as exc:
        raise sport_program_http_exception(exc) from exc


@router.get("/sport/program/active")
def get_active_sport_program(session: Session = Depends(get_session)) -> dict[str, Any]:
    user, _ = get_or_create_user(session)
    try:
        return sport_program_context(session, user.id)
    except SportProgramError as exc:
        raise sport_program_http_exception(exc) from exc


@router.get("/sport/progress")
def get_sport_progress(session: Session = Depends(get_session)) -> dict[str, Any]:
    user, _ = get_or_create_user(session)
    try:
        return build_sport_progress(session, user.id)
    except SportProgramError as exc:
        raise sport_program_http_exception(exc) from exc


@router.post("/sport/today", status_code=status.HTTP_201_CREATED)
def create_sport_today(
    payload: SportTodayRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    user, _ = get_or_create_user(session)
    sport_settings = profile_settings(session, user.id).get("sport", {})
    try:
        result = create_or_reuse_sport_today_workout(session, user.id, payload, sport_settings=sport_settings)
    except SportProgramError as exc:
        raise sport_program_http_exception(exc) from exc
    response.status_code = status.HTTP_200_OK if result["reused"] else status.HTTP_201_CREATED
    return result


@router.post("/sport/missed-day", status_code=status.HTTP_201_CREATED)
def record_sport_missed_day(payload: SportMissedDayRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    user, _ = get_or_create_user(session)
    try:
        return create_missed_day_adjustment(session, user.id, payload)
    except SportProgramError as exc:
        raise sport_program_http_exception(exc) from exc
