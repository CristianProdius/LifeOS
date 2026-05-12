from __future__ import annotations

from typing import Any


def build_daily_recommendations(
    capacity_minutes: int,
    tasks: list[dict[str, Any]],
    habits: list[dict[str, Any]],
) -> list[str]:
    recommendations = []
    if tasks:
        recommendations.append("Start with the highest-priority task before checking new inputs.")
    if habits:
        recommendations.append("Log the smallest version of each habit before the day gets noisy.")
    if capacity_minutes < 60:
        recommendations.append("Keep the plan narrow and protect recovery time.")
    else:
        recommendations.append("Leave at least one unscheduled buffer block.")
    return recommendations
