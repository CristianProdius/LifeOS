from __future__ import annotations

from typing import Any

from lifeos_api.models import LifeProfile


def profile_to_dict(profile: LifeProfile, personalization: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    payload = {
        "id": profile.id,
        "timezone": profile.timezone,
        "default_context": profile.default_context,
        "training_level": profile.training_level,
        "goals": profile.goals,
        "equipment": profile.equipment,
    }
    if personalization is not None:
        payload["personalization"] = personalization
    return payload
