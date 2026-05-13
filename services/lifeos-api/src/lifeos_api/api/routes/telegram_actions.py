from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from lifeos_api.api.deps import get_session
from lifeos_api.domain.telegram_actions import (
    InvalidCallbackDataError,
    TelegramResourceNotFoundError,
    UnsupportedTelegramActionError,
    apply_telegram_action,
)
from lifeos_api.schemas import TelegramActionRequest
from lifeos_api.seed import get_or_create_user

router = APIRouter()


@router.post("/telegram/actions")
def create_telegram_action(
    payload: TelegramActionRequest,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    user, _ = get_or_create_user(session)
    try:
        response = apply_telegram_action(
            session,
            user.id,
            callback_data=payload.callback_data,
            action_date=payload.action_date,
            value=payload.value,
            metadata=payload.metadata,
        )
    except InvalidCallbackDataError as exc:
        raise HTTPException(status_code=422, detail="invalid callback data") from exc
    except UnsupportedTelegramActionError as exc:
        raise HTTPException(
            status_code=422,
            detail="unsupported telegram action",
        ) from exc
    except TelegramResourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    session.commit()
    return response
