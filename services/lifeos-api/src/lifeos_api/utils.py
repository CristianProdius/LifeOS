from __future__ import annotations

import re
from datetime import date, datetime, time
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return slug.strip("-") or "item"


def money(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def rounded_metric(value: float) -> float | int:
    rounded = round(value, 2)
    return int(rounded) if rounded.is_integer() else rounded


def jsonable_data(value: Any) -> Any:
    if isinstance(value, dict):
        return {jsonable_data(key): jsonable_data(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [jsonable_data(item) for item in value]
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, Decimal):
        return money(float(value))
    if isinstance(value, Enum):
        return value.value
    return value
