from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from lifeos_api.api.deps import get_session
from lifeos_api.domain.context import AreaContextNotFoundError, get_area_context

router = APIRouter()


@router.get("/context/{area_slug}")
def get_context(area_slug: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    try:
        return get_area_context(session, area_slug)
    except AreaContextNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="area not found") from exc
