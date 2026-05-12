from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
from datetime import date
from typing import Any

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from lifeos_api.models import FinanceAccount, FinanceCategory, FinanceImport, FinanceTransaction, UploadedFile
from lifeos_api.schemas import FinanceAffordabilityRequest, FinanceImportDecisionRequest, FinanceImportRequest
from lifeos_api.serializers import finance_import_to_dict
from lifeos_api.utils import jsonable_data, money, slugify


class FinanceError(RuntimeError):
    """Raised when finance domain input cannot be processed."""

    detail = "finance error"
    status_code = 422

    def __init__(self, detail: str | None = None, status_code: int | None = None) -> None:
        self.detail = detail or self.detail
        self.status_code = status_code or self.status_code
        super().__init__(self.detail)


class FinanceTooManyRowsError(FinanceError):
    detail = "too many finance rows"


class FinanceMissingImportPayloadError(FinanceError):
    detail = "rows or file content is required"


class FinanceInvalidBase64Error(FinanceError):
    detail = "invalid base64 file content"


class FinanceFileTooLargeError(FinanceError):
    detail = "finance import file is too large"
    status_code = 413


class FinanceUnsupportedFileTypeError(FinanceError):
    detail = "unsupported finance import file type"


class FinanceUnsupportedXlsError(FinanceError):
    detail = "xls imports are not supported; export xlsx or csv"


class FinanceParseError(FinanceError):
    detail = "could not parse finance import file"


class FinanceRowMissingRequiredFieldsError(FinanceError):
    detail = "finance rows need date and amount"


class FinanceImportNotFoundError(FinanceError):
    detail = "finance import not found"
    status_code = 404


def rows_from_import_payload(payload: FinanceImportRequest) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if payload.rows is not None:
        if len(payload.rows) > 1000:
            raise FinanceTooManyRowsError()
        return payload.rows, None
    if not payload.content_base64 or not payload.file_name:
        raise FinanceMissingImportPayloadError()

    try:
        raw = base64.b64decode(payload.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise FinanceInvalidBase64Error() from exc
    if len(raw) > 5_000_000:
        raise FinanceFileTooLargeError()
    suffix = payload.file_name.lower().rsplit(".", 1)[-1]
    buffer = io.BytesIO(raw)
    try:
        if suffix == "xlsx":
            frame = pd.read_excel(buffer)
        elif suffix == "csv":
            frame = pd.read_csv(buffer)
        elif suffix == "xls":
            raise FinanceUnsupportedXlsError()
        else:
            raise FinanceUnsupportedFileTypeError()
    except FinanceError:
        raise
    except Exception as exc:
        raise FinanceParseError() from exc
    rows = frame.to_dict(orient="records")
    if len(rows) > 1000:
        raise FinanceTooManyRowsError()
    upload = {
        "file_name": payload.file_name,
        "content_type": payload.content_type,
        "byte_size": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    return rows, upload


def stage_finance_import(session: Session, user_id: int, payload: FinanceImportRequest) -> dict[str, Any]:
    rows, upload = rows_from_import_payload(payload)
    if upload is not None:
        maybe_store_upload(session, user_id, upload)

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
        review_items.append(jsonable_data(normalized))

    import_record = FinanceImport(
        user_id=user_id,
        source=payload.source,
        import_hash=import_hash,
        status="review_pending",
        raw_rows=jsonable_data(rows),
        review_items=review_items,
    )
    session.add(import_record)
    session.commit()
    session.refresh(import_record)
    return finance_import_to_dict(import_record, staged=len(review_items), skipped=0)


def approve_finance_import(
    session: Session,
    user_id: int,
    import_id: int,
    payload: FinanceImportDecisionRequest,
) -> dict[str, Any]:
    import_record = get_finance_import_or_404(session, user_id, import_id)
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

        account = get_or_create_account(session, user_id, item["account"], item["currency"])
        category = get_or_create_category(session, user_id, item["category"], float(item["amount"]))
        session.add(
            FinanceTransaction(
                user_id=user_id,
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


def reject_finance_import(
    session: Session,
    user_id: int,
    import_id: int,
    payload: FinanceImportDecisionRequest,
) -> dict[str, Any]:
    import_record = get_finance_import_or_404(session, user_id, import_id)
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


def finance_summary(session: Session, user_id: int) -> dict[str, Any]:
    transactions = session.scalars(select(FinanceTransaction).where(FinanceTransaction.user_id == user_id)).all()
    income = money(sum(tx.amount for tx in transactions if tx.amount > 0))
    expenses = money(abs(sum(tx.amount for tx in transactions if tx.amount < 0)))
    net = money(income - expenses)

    category_rows = session.execute(
        select(FinanceCategory.name, func.sum(FinanceTransaction.amount))
        .join(FinanceTransaction, FinanceTransaction.category_id == FinanceCategory.id)
        .where(FinanceTransaction.user_id == user_id)
        .group_by(FinanceCategory.name)
        .order_by(FinanceCategory.name)
    ).all()
    accounts = session.scalars(
        select(FinanceAccount).where(FinanceAccount.user_id == user_id).order_by(FinanceAccount.name)
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


def maybe_store_upload(session: Session, user_id: int, upload: dict[str, Any]) -> None:
    existing = session.scalar(select(UploadedFile).where(UploadedFile.sha256 == upload["sha256"]))
    if existing is None:
        session.add(UploadedFile(user_id=user_id, **upload))


def normalize_finance_row(row: dict[str, Any]) -> dict[str, Any]:
    raw_date = row.get("date") or row.get("transaction_date")
    raw_amount = row.get("amount")
    if raw_date is None or raw_amount is None:
        raise FinanceRowMissingRequiredFieldsError()
    tx_date = coerce_date(raw_date)
    amount = coerce_amount(raw_amount)
    return {
        "date": tx_date,
        "description": str(row.get("description") or row.get("name") or "Transaction").strip(),
        "amount": amount,
        "category": slugify(str(row.get("category") or ("income" if amount >= 0 else "uncategorized"))),
        "account": slugify(str(row.get("account") or "checking")),
        "currency": str(row.get("currency") or "USD").upper()[:3],
        "transaction_id": str(row.get("transaction_id") or row.get("id") or row.get("reference") or "").strip() or None,
    }


def coerce_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    if hasattr(value, "date"):
        return value.date()
    return date.fromisoformat(str(value)[:10])


def coerce_amount(value: Any) -> float:
    if isinstance(value, int | float):
        return float(value)
    text_value = str(value).strip().replace("$", "").replace(",", "")
    if text_value.startswith("(") and text_value.endswith(")"):
        text_value = f"-{text_value[1:-1]}"
    return float(text_value)


def transaction_external_id(source: str, import_hash: str, row_index: int, normalized: dict[str, Any]) -> str:
    if normalized.get("transaction_id"):
        raw = "|".join([source, "bank-id", str(normalized["transaction_id"]), normalized["account"]])
    else:
        raw = "|".join([source, import_hash, str(row_index)])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_or_create_account(session: Session, user_id: int, account_name: str, currency: str = "USD") -> FinanceAccount:
    account = session.scalar(
        select(FinanceAccount).where(FinanceAccount.user_id == user_id, FinanceAccount.name == account_name)
    )
    if account is None:
        account = FinanceAccount(user_id=user_id, name=account_name, currency=currency)
        session.add(account)
        session.flush()
    return account


def get_or_create_category(session: Session, user_id: int, category_slug: str, amount: float) -> FinanceCategory:
    category = session.scalar(
        select(FinanceCategory).where(FinanceCategory.user_id == user_id, FinanceCategory.slug == category_slug)
    )
    if category is None:
        category = FinanceCategory(
            user_id=user_id,
            slug=category_slug,
            name=category_slug.replace("-", " ").title(),
            kind="income" if amount >= 0 else "expense",
        )
        session.add(category)
        session.flush()
    return category


def get_finance_import_or_404(session: Session, user_id: int, import_id: int) -> FinanceImport:
    import_record = session.scalar(
        select(FinanceImport).where(FinanceImport.id == import_id, FinanceImport.user_id == user_id)
    )
    if import_record is None:
        raise FinanceImportNotFoundError()
    return import_record


def finance_import_status(review_items: list[dict[str, Any]]) -> str:
    statuses = {item.get("status") for item in review_items}
    if statuses <= {"approved", "duplicate"}:
        return "complete"
    if statuses <= {"rejected"}:
        return "rejected"
    return "review_pending"
