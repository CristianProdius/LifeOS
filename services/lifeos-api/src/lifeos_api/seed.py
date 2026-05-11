from __future__ import annotations

from datetime import date, timedelta

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
    SportGoal,
    TaskTemplate,
    Task,
    TrainingProgram,
    TrainingProgramWeek,
    User,
)
from lifeos_api.utils import slugify


DEFAULT_USER_EMAIL = "default@lifeos.local"
SPORT_PROGRAM_START = date(2026, 5, 11)
SPORT_PROGRAM_END = date(2027, 2, 8)
SPORT_STRETCH_DATE = date(2026, 8, 31)
SPORT_PROGRAM_WEEKS = 39


AREA_SEED = [
    ("daily", "Daily", "Morning launch, daily plan, non-negotiables, and status checks."),
    ("sport", "Sport", "Walking pad, pull-up bar, swimming, gym, recovery, and run/walk progression."),
    ("business", "Business", "Deep work, AI-use discipline, shipped deliverables, and NGO outreach."),
    ("finance", "Finance", "Cash flow, proposal fund, car payoff, budgets, imports, and affordability."),
    ("food", "Food", "Meal rhythm, sweets control, late eating, protein, and weight trend."),
    ("health", "Health", "Apple Health, Xiaomi scale, daily body metrics, and progress trends."),
    ("review", "Review", "Daily review, weekly review, lessons, blockers, and next plan."),
    ("admin", "Admin", "OpenClue setup, credentials, deployment, errors, and system maintenance."),
]


HABIT_SEED = [
    ("out-of-bed-0630", "Out of bed by 06:30", "daily", 1, "check"),
    ("no-phone-in-bed", "No phone in bed", "daily", 1, "check"),
    ("walking-done", "Walking done", "sport", 60, "minutes"),
    ("strength-swim-gym-done", "Strength, swim, or gym done", "sport", 1, "session"),
    ("no-porn", "No porn", "daily", 1, "check"),
    ("no-unplanned-sweets", "No unplanned sweets", "food", 1, "check"),
    ("no-late-eating", "No eating after 20:30", "food", 1, "check"),
    ("business-deliverable-shipped", "Business deliverable shipped", "business", 1, "deliverable"),
    ("ngo-outreach-done", "NGO outreach done", "business", 10, "messages"),
    ("weight-logged", "Weight logged", "food", 1, "entry"),
]


RESET_PLAN = [
    (1, "Book sleep apnea check", "daily", "Schedule a doctor consultation or sleep study discussion.", 5, 20),
    (2, "Set alarm across room", "daily", "Make the 06:30 wake-up require standing up within 30 seconds.", 5, 10),
    (3, "Order walking pad", "sport", "Choose a model with at least 130 kg support, ideally 140-150 kg.", 5, 45),
    (4, "Install pull-up bar", "sport", "Set up a safe pull-up bar and test dead hangs.", 4, 30),
    (5, "Remove sweets from office", "food", "Clear chocolates and sweets from the office and bedroom.", 5, 20),
    (6, "Write AI-use work rule", "business", "Before Claude or Codex, write problem, done state, constraints, and verification.", 5, 15),
    (7, "Create NGO outreach list", "business", "Collect the first 50 NGO leads for website or SEO outreach.", 4, 60),
    (8, "Send first 10 NGO messages", "business", "Send concise audit/outreach messages to 10 NGOs.", 5, 45),
    (9, "Define proposal fund envelope", "finance", "Create a 5000 USD proposal target and monthly saving line.", 5, 20),
    (10, "Define car payoff tracker", "finance", "Create a 10500 EUR car payoff target and note no early penalty.", 5, 20),
    (11, "Plan two reliable meals", "food", "Choose two repeatable meals with protein that reduce sweets risk.", 4, 30),
    (12, "Complete first weekly review", "review", "Review wake-ups, porn, sweets, walking, work shipped, and outreach.", 5, 45),
    (13, "Create week 2 task list", "review", "Turn the next seven days into concrete daily tasks.", 4, 30),
    (14, "Prepare OpenClue adjustment notes", "admin", "Record what the bot got wrong and what needs to be added next.", 4, 30),
]


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
                timezone="Europe/Chisinau",
                default_context="grandparents_home",
                training_level="beginner_returning",
                goals=["fat_loss", "consistency", "run_later"],
                equipment={"walking_pad": "planned", "pull_up_bar": "planned"},
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


def seed_sport_program(session: Session, user_id: int) -> dict[str, int]:
    created = 0
    latest_weight = session.scalar(
        select(HealthDailySummary.weight_kg)
        .where(HealthDailySummary.user_id == user_id, HealthDailySummary.weight_kg.is_not(None))
        .order_by(HealthDailySummary.summary_date.desc(), HealthDailySummary.updated_at.desc())
        .limit(1)
    )
    start_weight = round(float(latest_weight), 2) if latest_weight is not None else 117.0

    goal = session.scalar(select(SportGoal).where(SportGoal.user_id == user_id, SportGoal.name == "Cut to 90 kg"))
    if goal is None:
        goal = SportGoal(
            user_id=user_id,
            name="Cut to 90 kg",
            status="active",
            start_date=SPORT_PROGRAM_START,
            start_weight_kg=start_weight,
            target_weight_kg=90.0,
            target_date=SPORT_PROGRAM_END,
            stretch_weight_kg=95.0,
            stretch_date=SPORT_STRETCH_DATE,
            healthy_weekly_loss_min_kg=0.45,
            healthy_weekly_loss_max_kg=0.9,
            notes="Main goal is 90 kg as fast as healthy; 95 kg by 2026-08-31 is a stretch milestone.",
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
            TrainingProgram.name == "39-week fat loss base",
        )
    )
    if program is None:
        program = TrainingProgram(
            user_id=user_id,
            sport_goal_id=goal.id,
            name="39-week fat loss base",
            status="active",
            start_date=SPORT_PROGRAM_START,
            duration_weeks=SPORT_PROGRAM_WEEKS,
            current_week_number=1,
            default_location_context="grandparents_home",
            notes="Adaptive beginner-returning program emphasizing walking, consistency, strength basics, and safe progression.",
        )
        session.add(program)
        session.flush()
        created += 1

    for week_number in range(1, SPORT_PROGRAM_WEEKS + 1):
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
                phase=sport_phase_for_week(week_number),
                week_start=SPORT_PROGRAM_START + timedelta(days=(week_number - 1) * 7),
                week_end=SPORT_PROGRAM_START + timedelta(days=(week_number * 7) - 1),
                target_weight_kg=round(goal.start_weight_kg - ((goal.start_weight_kg - goal.target_weight_kg) * (week_number / SPORT_PROGRAM_WEEKS)), 2),
                target_steps_avg=sport_steps_for_week(week_number),
                target_active_minutes=sport_active_minutes_for_week(week_number),
                target_strength_sessions=1 if week_number <= 2 else 2 if week_number <= 12 else 3,
                target_cardio_sessions=3 if week_number <= 4 else 4 if week_number <= 24 else 5,
                target_recovery_sessions=2,
                plan_json=sport_week_plan_json(week_number),
            )
            session.add(week)
            created += 1

    session.commit()
    return {"created": created}


def sport_phase_for_week(week_number: int) -> str:
    if week_number <= 4:
        return "consistency_base"
    if week_number <= 12:
        return "weekly_rhythm"
    if week_number <= 24:
        return "fat_loss_engine"
    if week_number <= 32:
        return "run_walk_introduction"
    return "consolidation"


def sport_steps_for_week(week_number: int) -> int:
    return min(4500 + (week_number - 1) * 175, 9000)


def sport_active_minutes_for_week(week_number: int) -> int:
    if week_number <= 4:
        return 150
    if week_number <= 12:
        return 180
    if week_number <= 24:
        return 220
    return 240


def sport_week_plan_json(week_number: int) -> dict[str, object]:
    phase = sport_phase_for_week(week_number)
    return {
        "phase": phase,
        "days": [
            {"day": 1, "focus": "easy_cardio_strength"},
            {"day": 2, "focus": "walk_mobility"},
            {"day": 3, "focus": "easy_cardio"},
            {"day": 4, "focus": "strength_basics"},
            {"day": 5, "focus": "walk_mobility"},
            {"day": 6, "focus": "long_walk"},
            {"day": 7, "focus": "recovery"},
        ],
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
