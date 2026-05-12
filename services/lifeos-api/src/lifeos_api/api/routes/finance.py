from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from lifeos_api.api.deps import get_session
from lifeos_api.domain.finance import (
    FinanceError,
    approve_finance_import as approve_finance_import_domain,
    finance_affordability as finance_affordability_domain,
    finance_summary as finance_summary_domain,
    reject_finance_import as reject_finance_import_domain,
    stage_finance_import,
)
from lifeos_api.schemas import FinanceAffordabilityRequest, FinanceImportDecisionRequest, FinanceImportRequest
from lifeos_api.seed import get_or_create_user

router = APIRouter()


def finance_http_exception(exc: FinanceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.post("/finance/import", status_code=status.HTTP_201_CREATED)
def import_finance(payload: FinanceImportRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    user, _ = get_or_create_user(session)
    try:
        return stage_finance_import(session, user.id, payload)
    except FinanceError as exc:
        raise finance_http_exception(exc) from exc


@router.post("/finance/import/{import_id}/approve")
def approve_finance_import(
    import_id: int,
    payload: FinanceImportDecisionRequest,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    user, _ = get_or_create_user(session)
    try:
        return approve_finance_import_domain(session, user.id, import_id, payload)
    except FinanceError as exc:
        raise finance_http_exception(exc) from exc


@router.post("/finance/import/{import_id}/reject")
def reject_finance_import(
    import_id: int,
    payload: FinanceImportDecisionRequest,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    user, _ = get_or_create_user(session)
    try:
        return reject_finance_import_domain(session, user.id, import_id, payload)
    except FinanceError as exc:
        raise finance_http_exception(exc) from exc


@router.get("/finance")
def finance(session: Session = Depends(get_session)) -> dict[str, Any]:
    return finance_summary(session)


@router.get("/finance/summary")
def finance_summary(session: Session = Depends(get_session)) -> dict[str, Any]:
    user, _ = get_or_create_user(session)
    return finance_summary_domain(session, user.id)


@router.post("/finance/affordability")
def finance_affordability(payload: FinanceAffordabilityRequest) -> dict[str, Any]:
    return finance_affordability_domain(payload)
