from __future__ import annotations

from typing import Any

from lifeos_api.models import HealthDailySummary


def health_daily_summary_to_dict(summary: HealthDailySummary) -> dict[str, Any]:
    return {
        "id": summary.id,
        "summary_date": summary.summary_date,
        "source": summary.source,
        "sleep_duration_minutes": summary.sleep_duration_minutes,
        "sleep_quality": summary.sleep_quality,
        "weight_kg": summary.weight_kg,
        "body_fat_percent": summary.body_fat_percent,
        "bmi": summary.bmi,
        "steps": summary.steps,
        "active_energy_kcal": summary.active_energy_kcal,
        "workouts_count": summary.workouts_count,
        "resting_heart_rate": summary.resting_heart_rate,
        "average_heart_rate": summary.average_heart_rate,
        "notes": summary.notes,
        "created_at": summary.created_at,
        "updated_at": summary.updated_at,
    }
