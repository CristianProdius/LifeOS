from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from lifeos_api.api.deps import get_session
from lifeos_api.domain.profile import (
    deep_merge_settings,
    get_or_create_life_profile,
    get_or_create_profile_setting,
    profile_settings,
)
from lifeos_api.schemas import LifeProfileUpdate, ProfileSettingsPatch
from lifeos_api.seed import get_or_create_user
from lifeos_api.serializers import profile_to_dict
from lifeos_api.utils import slugify

router = APIRouter()


@router.get("/profile")
def get_profile(session: Session = Depends(get_session)) -> dict[str, Any]:
    user, _ = get_or_create_user(session)
    profile = get_or_create_life_profile(session, user.id)
    session.commit()
    session.refresh(profile)
    return profile_to_dict(profile, personalization=profile_settings(session, user.id))


@router.patch("/profile")
def update_profile(payload: LifeProfileUpdate, session: Session = Depends(get_session)) -> dict[str, Any]:
    user, _ = get_or_create_user(session)
    profile = get_or_create_life_profile(session, user.id)
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        if value is not None:
            setattr(profile, field, value)
    session.commit()
    session.refresh(profile)
    return profile_to_dict(profile)


@router.patch("/profile/settings/{domain}")
def update_profile_settings(
    domain: str,
    payload: ProfileSettingsPatch,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    user, _ = get_or_create_user(session)
    setting = get_or_create_profile_setting(session, user.id, slugify(domain))
    setting.settings = deep_merge_settings(setting.settings, payload.settings)
    flag_modified(setting, "settings")
    session.commit()
    session.refresh(setting)
    return setting.settings
