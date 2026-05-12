from __future__ import annotations

import json
from datetime import date, timedelta
from importlib.resources import files
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from lifeos_api.models import (
    Area,
    FinanceAccount,
    FinanceBudget,
    FinanceCategory,
    FinanceGoal,
    HabitDefinition,
    HealthDailySummary,
    LifeProfile,
    ProfileSetting,
    SportGoal,
    TaskTemplate,
    Task,
    TrainingProgram,
    TrainingProgramWeek,
    User,
)
from lifeos_api.utils import slugify


DEFAULT_USER_EMAIL = "default@lifeos.local"


def load_seed_json(name: str) -> Any:
    return json.loads((files("lifeos_api.data") / name).read_text(encoding="utf-8"))


AREA_SEED = [
    (area["slug"], area["name"], area["description"])
    for area in load_seed_json("areas.json")
]
HABIT_SEED = [
    (habit["slug"], habit["name"], habit["area_slug"], habit["target_value"], habit["unit"])
    for habit in load_seed_json("habits.json")
]
RESET_PLAN = [
    (
        task["reset_day"],
        task["title"],
        task["area_slug"],
        task["description"],
        task["priority"],
        task["estimated_minutes"],
    )
    for task in load_seed_json("reset_plan.json")
]
PERSONALIZATION_DATA = load_seed_json("personalization.json")
PROFILE_SEED = PERSONALIZATION_DATA["profile"]
PERSONALIZATION_SEED = PERSONALIZATION_DATA["settings"]
SPORT_PROGRAM_SEED = load_seed_json("sport_program.json")
SPORT_PROGRAM_GOAL_SEED = SPORT_PROGRAM_SEED["goal"]
SPORT_PROGRAM_SEED_DATA = SPORT_PROGRAM_SEED["program"]
SPORT_PROGRAM_WEEK_SEED = SPORT_PROGRAM_SEED["weeks"]
SPORT_PROGRAM_START = date.fromisoformat(SPORT_PROGRAM_GOAL_SEED["start_date"])
SPORT_PROGRAM_END = date.fromisoformat(SPORT_PROGRAM_GOAL_SEED["target_date"])
SPORT_STRETCH_DATE = date.fromisoformat(SPORT_PROGRAM_GOAL_SEED["stretch_date"])
SPORT_PROGRAM_WEEKS = int(SPORT_PROGRAM_SEED_DATA["duration_weeks"])


FINANCE_CATEGORIES = [
    ("income", "Income", "income"),
    ("housing", "Housing", "expense"),
    ("food", "Food", "expense"),
    ("transportation", "Transportation", "expense"),
    ("health", "Health", "expense"),
    ("dates", "Dates", "expense"),
    ("savings", "Savings", "transfer"),
    ("car", "Car", "debt"),
    ("proposal", "Proposal", "goal"),
]


def get_or_create_user(session: Session) -> tuple[User, bool]:
    user = session.scalar(select(User).where(User.email == DEFAULT_USER_EMAIL))
    if user:
        return user, False
    user = User(email=DEFAULT_USER_EMAIL, display_name="LifeOS User", timezone="UTC")
    session.add(user)
    session.flush()
    return user, True


def seed_reset_plan(session: Session) -> dict[str, int]:
    created = 0
    user, was_created = get_or_create_user(session)
    created += int(was_created)
    if user.timezone != "Europe/Chisinau":
        user.timezone = "Europe/Chisinau"

    areas: dict[str, Area] = {}
    for index, (slug, name, description) in enumerate(AREA_SEED, start=1):
        area = session.scalar(select(Area).where(Area.user_id == user.id, Area.slug == slug))
        if area is None:
            area = Area(user_id=user.id, slug=slug, name=name, description=description, sort_order=index)
            session.add(area)
            session.flush()
            created += 1
        areas[slug] = area

    for slug, name, area_slug, target, unit in HABIT_SEED:
        habit = session.scalar(select(HabitDefinition).where(HabitDefinition.user_id == user.id, HabitDefinition.slug == slug))
        if habit is None:
            session.add(
                HabitDefinition(
                    user_id=user.id,
                    area_id=areas[area_slug].id,
                    slug=slug,
                    name=name,
                    target_value=target,
                    unit=unit,
                    frequency="daily",
                )
            )
            created += 1

    for reset_day, title, area_slug, description, priority, minutes in RESET_PLAN:
        template = session.scalar(
            select(TaskTemplate).where(TaskTemplate.user_id == user.id, TaskTemplate.reset_day == reset_day)
        )
        if template is None:
            session.add(
                TaskTemplate(
                    user_id=user.id,
                    area_id=areas[area_slug].id,
                    reset_day=reset_day,
                    title=title,
                    description=description,
                    priority=priority,
                    estimated_minutes=minutes,
                )
            )
            created += 1
        due_date = date.today() + timedelta(days=reset_day - 1)
        existing_task = session.scalar(
            select(Task).where(Task.user_id == user.id, Task.title == title, Task.due_date == due_date)
        )
        if existing_task is None:
            session.add(
                Task(
                    user_id=user.id,
                    area_id=areas[area_slug].id,
                    template_id=template.id if template is not None else None,
                    title=title,
                    notes=description,
                    status="todo",
                    priority=priority,
                    due_date=due_date,
                )
            )
            created += 1

    categories: dict[str, FinanceCategory] = {}
    for slug, name, kind in FINANCE_CATEGORIES:
        category = session.scalar(
            select(FinanceCategory).where(FinanceCategory.user_id == user.id, FinanceCategory.slug == slug)
        )
        if category is None:
            category = FinanceCategory(user_id=user.id, slug=slug, name=name, kind=kind)
            session.add(category)
            session.flush()
            created += 1
        categories[slug] = category

    account = session.scalar(select(FinanceAccount).where(FinanceAccount.user_id == user.id, FinanceAccount.name == "checking"))
    if account is None:
        session.add(FinanceAccount(user_id=user.id, name="checking", account_type="checking"))
        created += 1

    profile = session.scalar(select(LifeProfile).where(LifeProfile.user_id == user.id))
    if profile is None:
        session.add(
            LifeProfile(
                user_id=user.id,
                timezone=PROFILE_SEED["timezone"],
                default_context=PROFILE_SEED["default_context"],
                training_level=PROFILE_SEED["training_level"],
                goals=PROFILE_SEED["goals"],
                equipment=PROFILE_SEED["equipment"],
            )
        )
        created += 1

    for domain, settings in PERSONALIZATION_SEED.items():
        profile_setting = session.scalar(
            select(ProfileSetting).where(ProfileSetting.user_id == user.id, ProfileSetting.domain == domain)
        )
        if profile_setting is None:
            session.add(ProfileSetting(user_id=user.id, domain=domain, settings=settings))
            created += 1
        else:
            merged = merge_missing_settings(profile_setting.settings, settings)
            if merged != profile_setting.settings:
                profile_setting.settings = merged

    kitchen_scale = session.scalar(select(Task).where(Task.user_id == user.id, Task.title == "Buy kitchen scale"))
    if kitchen_scale is None:
        session.add(
            Task(
                user_id=user.id,
                area_id=areas["food"].id,
                title="Buy kitchen scale",
                notes="Needed for strict calorie tracking; weigh calorie-dense foods once available.",
                status="todo",
                priority=4,
                due_date=date.today() + timedelta(days=7),
            )
        )
        created += 1

    month = date(2026, 5, 1)
    dates_budget = session.scalar(
        select(FinanceBudget).where(
            FinanceBudget.user_id == user.id,
            FinanceBudget.category_id == categories["dates"].id,
            FinanceBudget.month == month,
        )
    )
    if dates_budget is None:
        session.add(FinanceBudget(user_id=user.id, category_id=categories["dates"].id, month=month, amount=100))
        created += 1

    goal_seed = [
        ("emergency-buffer", "Emergency buffer", 1000, 0),
        ("proposal-fund", "Proposal fund", 5000, 0),
        ("car-payoff", "Car payoff", 10500, 0),
    ]
    for slug, name, target_amount, current_amount in goal_seed:
        goal = session.scalar(select(FinanceGoal).where(FinanceGoal.user_id == user.id, FinanceGoal.slug == slug))
        if goal is None:
            session.add(
                FinanceGoal(
                    user_id=user.id,
                    slug=slug,
                    name=name,
                    target_amount=target_amount,
                    current_amount=current_amount,
                )
            )
            created += 1

    session.commit()
    created += seed_sport_program(session, user.id)["created"]
    return {"created": created}


def merge_missing_settings(existing: dict, defaults: dict) -> dict:
    merged = dict(existing or {})
    for key, default_value in defaults.items():
        existing_value = merged.get(key)
        if key not in merged:
            merged[key] = default_value
        elif isinstance(existing_value, dict) and isinstance(default_value, dict):
            merged[key] = merge_missing_settings(existing_value, default_value)
    return merged


def seed_sport_program(session: Session, user_id: int) -> dict[str, int]:
    created = 0
    latest_weight = session.scalar(
        select(HealthDailySummary.weight_kg)
        .where(HealthDailySummary.user_id == user_id, HealthDailySummary.weight_kg.is_not(None))
        .order_by(HealthDailySummary.summary_date.desc(), HealthDailySummary.updated_at.desc())
        .limit(1)
    )
    start_weight = (
        round(float(latest_weight), 2)
        if latest_weight is not None
        else float(SPORT_PROGRAM_SEED["default_start_weight_kg"])
    )

    goal = session.scalar(select(SportGoal).where(SportGoal.user_id == user_id, SportGoal.name == SPORT_PROGRAM_GOAL_SEED["name"]))
    if goal is None:
        goal = SportGoal(
            user_id=user_id,
            name=SPORT_PROGRAM_GOAL_SEED["name"],
            status=SPORT_PROGRAM_GOAL_SEED["status"],
            start_date=SPORT_PROGRAM_START,
            start_weight_kg=start_weight,
            target_weight_kg=SPORT_PROGRAM_GOAL_SEED["target_weight_kg"],
            target_date=SPORT_PROGRAM_END,
            stretch_weight_kg=SPORT_PROGRAM_GOAL_SEED["stretch_weight_kg"],
            stretch_date=SPORT_STRETCH_DATE,
            healthy_weekly_loss_min_kg=SPORT_PROGRAM_GOAL_SEED["healthy_weekly_loss_min_kg"],
            healthy_weekly_loss_max_kg=SPORT_PROGRAM_GOAL_SEED["healthy_weekly_loss_max_kg"],
            notes=SPORT_PROGRAM_GOAL_SEED["notes"],
        )
        session.add(goal)
        session.flush()
        created += 1
    elif goal.status != "active":
        goal.status = "active"

    program = session.scalar(
        select(TrainingProgram).where(
            TrainingProgram.user_id == user_id,
            TrainingProgram.sport_goal_id == goal.id,
            TrainingProgram.name == SPORT_PROGRAM_SEED_DATA["name"],
        )
    )
    if program is None:
        program = TrainingProgram(
            user_id=user_id,
            sport_goal_id=goal.id,
            name=SPORT_PROGRAM_SEED_DATA["name"],
            status=SPORT_PROGRAM_SEED_DATA["status"],
            start_date=SPORT_PROGRAM_START,
            duration_weeks=SPORT_PROGRAM_WEEKS,
            current_week_number=SPORT_PROGRAM_SEED_DATA["current_week_number"],
            default_location_context=SPORT_PROGRAM_SEED_DATA["default_location_context"],
            notes=SPORT_PROGRAM_SEED_DATA["notes"],
        )
        session.add(program)
        session.flush()
        created += 1
    elif program.status != "active":
        program.status = "active"

    for week_seed in SPORT_PROGRAM_WEEK_SEED:
        week_number = week_seed["week_number"]
        week = session.scalar(
            select(TrainingProgramWeek).where(
                TrainingProgramWeek.program_id == program.id,
                TrainingProgramWeek.week_number == week_number,
            )
        )
        if week is None:
            week = TrainingProgramWeek(
                program_id=program.id,
                week_number=week_number,
                phase=week_seed["phase"],
                week_start=date.fromisoformat(week_seed["week_start"]),
                week_end=date.fromisoformat(week_seed["week_end"]),
                target_weight_kg=round(goal.start_weight_kg - ((goal.start_weight_kg - goal.target_weight_kg) * (week_number / SPORT_PROGRAM_WEEKS)), 2),
                target_steps_avg=week_seed["target_steps_avg"],
                target_active_minutes=week_seed["target_active_minutes"],
                target_strength_sessions=week_seed["target_strength_sessions"],
                target_cardio_sessions=week_seed["target_cardio_sessions"],
                target_recovery_sessions=week_seed["target_recovery_sessions"],
                plan_json=sport_week_plan_json(week_seed),
            )
            session.add(week)
            created += 1

    session.commit()
    return {"created": created}


def sport_week_plan_json(week_seed: dict[str, Any]) -> dict[str, object]:
    return {
        "phase": week_seed["phase"],
        "days": SPORT_PROGRAM_SEED["plan_days"],
    }


def ensure_area(session: Session, user_id: int, area_name: str) -> Area:
    slug = slugify(area_name)
    area = session.scalar(select(Area).where(Area.user_id == user_id, Area.slug == slug))
    if area:
        return area
    area = Area(user_id=user_id, slug=slug, name=area_name.strip().title(), sort_order=100)
    session.add(area)
    session.flush()
    return area


def main() -> None:
    from lifeos_api.database import create_engine_and_session, init_database

    engine, session_factory = create_engine_and_session()
    init_database(engine)
    with session_factory() as session:
        result = seed_reset_plan(session)
    print(f"LifeOS seed complete: created={result['created']}")


if __name__ == "__main__":
    main()
