from __future__ import annotations

from typing import Any

from lifeos_api.models import FinanceImport


def finance_import_to_dict(
    import_record: FinanceImport,
    *,
    staged: int | None = None,
    imported: int = 0,
    skipped: int = 0,
    rejected: int = 0,
) -> dict[str, Any]:
    review_items = import_record.review_items or []
    return {
        "id": import_record.id,
        "source": import_record.source,
        "status": import_record.status,
        "staged": len(review_items) if staged is None else staged,
        "imported": imported,
        "imported_total": import_record.imported_count,
        "skipped": skipped,
        "rejected": rejected,
        "review_items": review_items,
    }
