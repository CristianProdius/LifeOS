from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from lifeos_api.api.deps import get_session
from lifeos_api.domain.finance import (
    FinanceError,
    coerce_date,
    finance_import_status,
    get_finance_import_or_404,
    get_or_create_account,
    get_or_create_category,
    maybe_store_upload,
    normalize_finance_row,
    rows_from_import_payload,
    transaction_external_id,
)
from lifeos_api.models import FinanceAccount, FinanceCategory, FinanceImport, FinanceTransaction
from lifeos_api.schemas import FinanceAffordabilityRequest, FinanceImportDecisionRequest, FinanceImportRequest
from lifeos_api.seed import get_or_create_user
from lifeos_api.serializers import finance_import_to_dict
from lifeos_api.utils import money

router = APIRouter()


def finance_http_exception(exc: FinanceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.post("/finance/import", status_code=status.HTTP_201_CREATED)
def import_finance(payload: FinanceImportRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    user, _ = get_or_create_user(session)
    try:
        rows, upload = rows_from_import_payload(payload)
        if upload is not None:
            maybe_store_upload(session, user.id, upload)

        import_hash = hashlib.sha256(
            json.dumps({"source": payload.source, "rows": rows}, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        existing_import = session.scalar(select(FinanceImport).where(FinanceImport.import_hash == import_hash))
        if existing_import is not None:
            return {
                "id": existing_import.id,
                "source": existing_import.source,
                "status": "duplicate",
                "staged": 0,
                "skipped": len(rows),
                "review_items": existing_import.review_items,
            }

        review_items = []
        for row_index, row in enumerate(rows):
            normalized = normalize_finance_row(row)
            normalized["row_index"] = row_index
            normalized["external_id"] = transaction_external_id(payload.source, import_hash, row_index, normalized)
            normalized["status"] = "pending"
            review_items.append(jsonable_encoder(normalized))

        import_record = FinanceImport(
            user_id=user.id,
            source=payload.source,
            import_hash=import_hash,
            status="review_pending",
            raw_rows=jsonable_encoder(rows),
            review_items=review_items,
        )
        session.add(import_record)
        session.commit()
        session.refresh(import_record)
        return finance_import_to_dict(import_record, staged=len(review_items), skipped=0)
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
        import_record = get_finance_import_or_404(session, user.id, import_id)
        selected = set(payload.row_indexes) if payload.row_indexes is not None else None
        review_items = list(import_record.review_items or [])
        imported = 0
        skipped = 0

        for item in review_items:
            row_index = int(item["row_index"])
            if selected is not None and row_index not in selected:
                continue
            if item.get("status") in {"approved", "rejected"}:
                skipped += 1
                continue
            existing = session.scalar(
                select(FinanceTransaction).where(FinanceTransaction.external_id == item["external_id"])
            )
            if existing is not None:
                item["status"] = "duplicate"
                skipped += 1
                continue

            account = get_or_create_account(session, user.id, item["account"], item["currency"])
            category = get_or_create_category(session, user.id, item["category"], float(item["amount"]))
            session.add(
                FinanceTransaction(
                    user_id=user.id,
                    account_id=account.id,
                    category_id=category.id,
                    import_id=import_record.id,
                    transaction_date=coerce_date(item["date"]),
                    description=item["description"],
                    amount=float(item["amount"]),
                    currency=item["currency"],
                    external_id=item["external_id"],
                )
            )
            item["status"] = "approved"
            imported += 1

        import_record.review_items = review_items
        flag_modified(import_record, "review_items")
        import_record.imported_count += imported
        import_record.status = finance_import_status(review_items)
        session.commit()
        session.refresh(import_record)
        return finance_import_to_dict(import_record, imported=imported, skipped=skipped)
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
        import_record = get_finance_import_or_404(session, user.id, import_id)
        selected = set(payload.row_indexes) if payload.row_indexes is not None else None
        review_items = list(import_record.review_items or [])
        rejected = 0
        for item in review_items:
            row_index = int(item["row_index"])
            if selected is not None and row_index not in selected:
                continue
            if item.get("status") == "pending":
                item["status"] = "rejected"
                rejected += 1
        import_record.review_items = review_items
        flag_modified(import_record, "review_items")
        import_record.status = finance_import_status(review_items)
        session.commit()
        session.refresh(import_record)
        return finance_import_to_dict(import_record, rejected=rejected)
    except FinanceError as exc:
        raise finance_http_exception(exc) from exc


@router.get("/finance")
def finance(session: Session = Depends(get_session)) -> dict[str, Any]:
    return finance_summary(session)


@router.get("/finance/summary")
def finance_summary(session: Session = Depends(get_session)) -> dict[str, Any]:
    user, _ = get_or_create_user(session)
    transactions = session.scalars(select(FinanceTransaction).where(FinanceTransaction.user_id == user.id)).all()
    income = money(sum(tx.amount for tx in transactions if tx.amount > 0))
    expenses = money(abs(sum(tx.amount for tx in transactions if tx.amount < 0)))
    net = money(income - expenses)

    category_rows = session.execute(
        select(FinanceCategory.name, func.sum(FinanceTransaction.amount))
        .join(FinanceTransaction, FinanceTransaction.category_id == FinanceCategory.id)
        .where(FinanceTransaction.user_id == user.id)
        .group_by(FinanceCategory.name)
        .order_by(FinanceCategory.name)
    ).all()
    accounts = session.scalars(
        select(FinanceAccount).where(FinanceAccount.user_id == user.id).order_by(FinanceAccount.name)
    ).all()

    return {
        "income": income,
        "expenses": expenses,
        "net": net,
        "by_category": [{"category": name, "amount": money(amount or 0)} for name, amount in category_rows],
        "accounts": [
            {
                "name": account.name,
                "posted_balance": money(account.balance),
                "currency": account.currency,
                "balance_source": "manual_or_bank_reported",
            }
            for account in accounts
        ],
    }


@router.post("/finance/affordability")
def finance_affordability(payload: FinanceAffordabilityRequest) -> dict[str, Any]:
    remaining_needed = max(payload.purchase_amount - payload.current_savings, 0)
    monthly_savings_needed = money(remaining_needed / payload.months)
    monthly_surplus = money(payload.monthly_income - payload.monthly_expenses)
    projected_remaining = money((monthly_surplus * payload.months) + payload.current_savings - payload.purchase_amount)
    affordable = monthly_savings_needed <= monthly_surplus
    recommendation = (
        "Affordable within the requested timeline."
        if affordable
        else "Delay, reduce scope, or increase monthly surplus before buying."
    )
    return {
        "affordable": affordable,
        "monthly_savings_needed": monthly_savings_needed,
        "monthly_surplus": monthly_surplus,
        "projected_remaining": projected_remaining,
        "recommendation": recommendation,
    }
