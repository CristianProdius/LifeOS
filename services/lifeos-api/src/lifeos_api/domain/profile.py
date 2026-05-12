from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from lifeos_api.core.time import LIFEOS_DEFAULT_TIMEZONE
from lifeos_api.models import LifeProfile, ProfileSetting
from lifeos_api.seed import PERSONALIZATION_SEED

DEFAULT_PROFILE = {
    "timezone": LIFEOS_DEFAULT_TIMEZONE,
    "default_context": "grandparents_home",
    "training_level": "beginner_returning",
    "goals": ["fat_loss", "consistency", "run_later"],
    "equipment": {"walking_pad": "planned", "pull_up_bar": "planned"},
}


def get_or_create_life_profile(session: Session, user_id: int) -> LifeProfile:
    profile = session.scalar(select(LifeProfile).where(LifeProfile.user_id == user_id))
    if profile is None:
        profile = LifeProfile(user_id=user_id, **DEFAULT_PROFILE)
        session.add(profile)
        session.flush()
    return profile


def profile_settings(session: Session, user_id: int) -> dict[str, dict[str, Any]]:
    settings = session.scalars(
        select(ProfileSetting).where(ProfileSetting.user_id == user_id).order_by(ProfileSetting.domain)
    ).all()
    return {setting.domain: setting.settings for setting in settings}


def get_or_create_profile_setting(session: Session, user_id: int, domain: str) -> ProfileSetting:
    setting = session.scalar(
        select(ProfileSetting).where(ProfileSetting.user_id == user_id, ProfileSetting.domain == domain)
    )
    if setting is None:
        setting = ProfileSetting(user_id=user_id, domain=domain, settings=PERSONALIZATION_SEED.get(domain, {}))
        session.add(setting)
        session.flush()
    return setting


def deep_merge_settings(existing: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing or {})
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge_settings(merged[key], value)
        else:
            merged[key] = value
    return merged


def context_personalization(area_slug: str, settings: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    domains_by_area = {
        "sport": ["sport", "daily", "coaching"],
        "food": ["food", "coaching"],
        "daily": ["daily", "sport", "food", "coaching"],
        "health": ["sport", "food", "daily", "coaching"],
    }
    return {domain: settings[domain] for domain in domains_by_area.get(area_slug, []) if domain in settings}
