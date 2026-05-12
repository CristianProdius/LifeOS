from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from lifeos_api.api.deps import get_session
from lifeos_api.domain.health import upsert_health_summary
from lifeos_api.schemas import HealthDailySummaryUpsert, HealthResponse
from lifeos_api.serializers import health_daily_summary_to_dict

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health(request: Request, session: Session = Depends(get_session)) -> dict[str, Any]:
    try:
        session.execute(text("select 1"))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="database unavailable") from exc
    return {"status": "ok", "database": "ok", "seeded": request.app.state.seeded}


@router.post("/health/daily-summaries", status_code=status.HTTP_201_CREATED)
def upsert_health_daily_summary(
    payload: HealthDailySummaryUpsert,
    response: Response,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    summary, created = upsert_health_summary(payload, session)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return health_daily_summary_to_dict(summary)


@router.post("/integrations/shortcuts/health-daily-summary", status_code=status.HTTP_201_CREATED)
def ingest_shortcut_health_daily_summary(
    payload: HealthDailySummaryUpsert,
    response: Response,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    summary, created = upsert_health_summary(payload, session)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return health_daily_summary_to_dict(summary)
