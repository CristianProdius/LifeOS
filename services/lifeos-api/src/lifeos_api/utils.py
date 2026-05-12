from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_UP


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return slug.strip("-") or "item"


def money(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def rounded_metric(value: float) -> float | int:
    rounded = round(value, 2)
    return int(rounded) if rounded.is_integer() else rounded
