from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from lifeos_api.models import HealthDailySummary
from lifeos_api.schemas import HealthDailySummaryUpsert
from lifeos_api.seed import get_or_create_user
from lifeos_api.utils import rounded_metric

HEALTH_PROGRESS_METRICS = (
    "steps",
    "active_energy_kcal",
    "weight_kg",
    "body_fat_percent",
    "bmi",
    "resting_heart_rate",
    "average_heart_rate",
)


def upsert_health_summary(payload: HealthDailySummaryUpsert, session: Session) -> tuple[HealthDailySummary, bool]:
    user, _ = get_or_create_user(session)
    summary = session.scalar(
        select(HealthDailySummary).where(
            HealthDailySummary.user_id == user.id,
            HealthDailySummary.summary_date == payload.summary_date,
            HealthDailySummary.source == payload.source,
        )
    )
    created = summary is None
    if summary is None:
        summary = HealthDailySummary(
            user_id=user.id,
            summary_date=payload.summary_date,
            source=payload.source,
        )
        session.add(summary)
    updates = payload.model_dump(exclude_unset=True)
    updates.pop("summary_date", None)
    updates.pop("source", None)
    for field, value in updates.items():
        setattr(summary, field, value)
    session.commit()
    session.refresh(summary)
    return summary, created


def build_health_progress(summaries: list[HealthDailySummary]) -> dict[str, Any]:
    ordered = sorted(summaries, key=lambda item: (item.summary_date, item.updated_at), reverse=True)
    latest = ordered[0] if ordered else None
    previous = next(
        (summary for summary in ordered[1:] if latest is not None and summary.summary_date < latest.summary_date),
        None,
    )
    latest_metrics = health_metric_values(latest) if latest else {}
    previous_metrics = health_metric_values(previous) if previous else {}

    averages: dict[str, float | int] = {}
    deltas: dict[str, float | int | None] = {}
    for metric in HEALTH_PROGRESS_METRICS:
        values = [getattr(summary, metric) for summary in ordered if getattr(summary, metric) is not None]
        if values:
            averages[metric] = rounded_metric(sum(float(value) for value in values) / len(values))
        latest_value = latest_metrics.get(metric)
        previous_value = previous_metrics.get(metric)
        deltas[metric] = (
            rounded_metric(float(latest_value) - float(previous_value))
            if latest_value is not None and previous_value is not None
            else None
        )

    days_available = len({summary.summary_date for summary in ordered})
    metric_days_available = {
        metric: len({summary.summary_date for summary in ordered if getattr(summary, metric) is not None})
        for metric in HEALTH_PROGRESS_METRICS
    }
    has_latest = latest is not None
    has_trend = days_available >= 2
    missing_latest_metrics = [
        metric for metric in HEALTH_PROGRESS_METRICS if latest_metrics.get(metric) is None
    ] if latest else list(HEALTH_PROGRESS_METRICS)

    return {
        "latest": health_progress_summary_to_dict(latest) if latest else None,
        "previous": health_progress_summary_to_dict(previous) if previous else None,
        "seven_day_average": averages,
        "deltas": deltas,
        "data_quality": {
            "summary_count": len(ordered),
            "days_available": days_available,
            "metric_days_available": metric_days_available,
            "has_latest": has_latest,
            "has_trend": has_trend,
            "trend_status": "available" if has_trend else "needs_more_data" if has_latest else "no_data",
            "missing_latest_metrics": missing_latest_metrics,
        },
    }


def health_metric_values(summary: HealthDailySummary | None) -> dict[str, Any]:
    if summary is None:
        return {metric: None for metric in HEALTH_PROGRESS_METRICS}
    return {metric: getattr(summary, metric) for metric in HEALTH_PROGRESS_METRICS}


def health_progress_summary_to_dict(summary: HealthDailySummary) -> dict[str, Any]:
    return {
        "id": summary.id,
        "summary_date": summary.summary_date,
        "source": summary.source,
        "metrics": health_metric_values(summary),
        "updated_at": summary.updated_at,
    }
