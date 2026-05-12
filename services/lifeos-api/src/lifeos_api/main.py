from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import os
from datetime import date, timedelta
from typing import Any

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.attributes import flag_modified

from lifeos_api.api.deps import get_session
from lifeos_api.core.security import require_api_key
from lifeos_api.core.time import LIFEOS_DEFAULT_TIMEZONE, lifeos_today
from lifeos_api.database import create_engine_and_session, get_database_url, init_database
from lifeos_api.domain.food import (
    FOOD_LOG_STATUSES,
    FoodLogNotFoundError,
    build_food_daily_summary,
    build_food_progress_context,
    create_food_target,
    food_log_item_from_payload,
    get_food_log_or_404,
    get_or_create_active_food_target,
)
from lifeos_api.domain.health import build_health_progress, upsert_health_summary
from lifeos_api.domain.workouts import (
    PLANNED_WORKOUT_STATUSES,
    PlannedWorkoutNotFoundError,
    build_planned_workout,
    build_workout_recommendation,
    exercise_payload_from_plan,
    get_planned_workout_or_404,
)
from lifeos_api.models import (
    AdviceLog,
    Area,
    Checkin,
    DailyPlan,
    DailyReview,
    FinanceAccount,
    FinanceCategory,
    FinanceImport,
    FinanceTransaction,
    FoodDailyReview,
    FoodLog,
    HabitDefinition,
    HabitLog,
    HealthDailySummary,
    LifeProfile,
    PlannedWorkout,
    ProfileSetting,
    ProgramAdjustment,
    SportGoal,
    Task,
    TrainingProgram,
    TrainingProgramWeek,
    UploadedFile,
    WeeklyReview,
    WorkoutExercise,
    WorkoutSession,
    utc_now,
)
from lifeos_api.schemas import (
    CheckinCreate,
    DailyPlanRequest,
    DailyReviewCreate,
    FinanceAffordabilityRequest,
    FinanceImportDecisionRequest,
    FinanceImportRequest,
    FoodDailyReviewCreate,
    FoodLogCreate,
    FoodLogItemPayload,
    FoodLogUpdate,
    FoodTargetRecalculate,
    HabitLogCreate,
    HealthDailySummaryUpsert,
    HealthResponse,
    LifeProfileUpdate,
    ProfileSettingsPatch,
    SportMissedDayRequest,
    SportTodayRequest,
    TaskCreate,
    TaskUpdate,
    WeeklyReviewCreate,
    WorkoutLogCreate,
    WorkoutPlanComplete,
    WorkoutPlanCreate,
    WorkoutPlanUpdate,
    WorkoutRecommendationRequest,
)
from lifeos_api.serializers import (
    area_to_dict,
    checkin_to_dict,
    daily_plan_to_dict,
    daily_review_to_dict,
    finance_import_to_dict,
    food_daily_review_to_dict,
    food_log_to_dict,
    food_target_to_dict,
    habit_log_to_dict,
    habit_to_dict,
    health_daily_summary_to_dict,
    planned_workout_to_dict,
    profile_to_dict,
    program_adjustment_to_dict,
    sport_goal_to_dict,
    task_to_dict,
    training_program_to_dict,
    training_program_week_to_dict,
    weekly_review_to_dict,
    workout_to_dict,
)
from lifeos_api.seed import PERSONALIZATION_SEED, ensure_area, get_or_create_user, seed_reset_plan, seed_sport_program
from lifeos_api.utils import money, rounded_metric, slugify

DEFAULT_PROFILE = {
    "timezone": LIFEOS_DEFAULT_TIMEZONE,
    "default_context": "grandparents_home",
    "training_level": "beginner_returning",
    "goals": ["fat_loss", "consistency", "run_later"],
    "equipment": {"walking_pad": "planned", "pull_up_bar": "planned"},
}

def create_app(database_url: str | None = None, seed_database: bool = True) -> FastAPI:
    engine, session_factory = create_engine_and_session(database_url)
    effective_database_url = database_url or get_database_url()
    auto_create_schema = effective_database_url.startswith("sqlite") or os.getenv("LIFEOS_AUTO_CREATE_SCHEMA", "").lower() in {
        "1",
        "true",
        "yes",
    }
    if auto_create_schema:
        init_database(engine)

    seeded = False
    if seed_database:
        with session_factory() as session:
            seed_reset_plan(session)
            seeded = True

    app = FastAPI(
        title="LifeOS API",
        version="0.1.0",
        description="OpenClue LifeOS FastAPI service.",
        dependencies=[Depends(require_api_key)],
    )
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.seeded = seeded

    @app.get("/health", response_model=HealthResponse)
    def health(session: Session = Depends(get_session)) -> dict[str, Any]:
        try:
            session.execute(text("select 1"))
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="database unavailable") from exc
        return {"status": "ok", "database": "ok", "seeded": app.state.seeded}

    @app.get("/profile")
    def get_profile(session: Session = Depends(get_session)) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        profile = get_or_create_life_profile(session, user.id)
        session.commit()
        session.refresh(profile)
        return profile_to_dict(profile, personalization=profile_settings(session, user.id))

    @app.patch("/profile")
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

    @app.patch("/profile/settings/{domain}")
    def update_profile_settings(domain: str, payload: ProfileSettingsPatch, session: Session = Depends(get_session)) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        setting = get_or_create_profile_setting(session, user.id, slugify(domain))
        setting.settings = deep_merge_settings(setting.settings, payload.settings)
        flag_modified(setting, "settings")
        session.commit()
        session.refresh(setting)
        return setting.settings

    @app.get("/context/{area_slug}")
    def get_context(area_slug: str, session: Session = Depends(get_session)) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        normalized_area_slug = slugify(area_slug)
        area = session.scalar(select(Area).where(Area.user_id == user.id, Area.slug == normalized_area_slug))
        if area is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="area not found")

        tasks = session.scalars(
            select(Task)
            .where(Task.user_id == user.id, Task.area_id == area.id)
            .order_by(Task.priority.desc(), Task.created_at.desc())
        ).all()
        habits = session.scalars(
            select(HabitDefinition)
            .where(HabitDefinition.user_id == user.id, HabitDefinition.area_id == area.id, HabitDefinition.is_active.is_(True))
            .order_by(HabitDefinition.name)
        ).all()
        checkins = session.scalars(
            select(Checkin)
            .where(Checkin.user_id == user.id, Checkin.area_id == area.id)
            .order_by(Checkin.created_at.desc())
            .limit(5)
        ).all()

        context = {
            "area": area_to_dict(area),
            "tasks": [task_to_dict(task) for task in tasks],
            "habits": [habit_to_dict(habit) for habit in habits],
            "recent_checkins": [checkin_to_dict(checkin) for checkin in checkins],
        }
        if normalized_area_slug in {"sport", "daily", "food", "health"}:
            health_summaries = session.scalars(
                select(HealthDailySummary)
                .where(HealthDailySummary.user_id == user.id)
                .order_by(HealthDailySummary.summary_date.desc(), HealthDailySummary.updated_at.desc())
                .limit(7)
            ).all()
            settings = profile_settings(session, user.id)
            context["profile"] = profile_to_dict(get_or_create_life_profile(session, user.id))
            context["personalization"] = context_personalization(normalized_area_slug, settings)
            context["recent_health_summaries"] = [health_daily_summary_to_dict(summary) for summary in health_summaries]
            context["health_progress"] = build_health_progress(health_summaries)
        if normalized_area_slug == "food":
            target = get_or_create_active_food_target(session, user.id)
            today = lifeos_today()
            context["food_target"] = food_target_to_dict(target)
            context["today_food_summary"] = build_food_daily_summary(session, user.id, today, target)
            context["food_progress"] = build_food_progress_context(session, user.id, today, target)
            session.commit()
        if normalized_area_slug == "sport":
            active_plan = session.scalar(
                select(PlannedWorkout)
                .where(
                    PlannedWorkout.user_id == user.id,
                    PlannedWorkout.status.in_(["proposed", "accepted", "started"]),
                )
                .order_by(PlannedWorkout.plan_date.desc(), PlannedWorkout.created_at.desc())
            )
            latest_workout = session.scalar(
                select(WorkoutSession)
                .where(WorkoutSession.user_id == user.id)
                .order_by(WorkoutSession.session_date.desc(), WorkoutSession.created_at.desc())
            )
            context["active_planned_workout"] = planned_workout_to_dict(active_plan) if active_plan else None
            context["latest_workout"] = workout_to_dict(latest_workout) if latest_workout else None
        return context

    @app.post("/sport/program/seed")
    def seed_sport_program_endpoint(response: Response, session: Session = Depends(get_session)) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        result = seed_sport_program(session, user.id)
        response.status_code = status.HTTP_201_CREATED if result["created"] else status.HTTP_200_OK
        return sport_program_context(session, user.id)

    @app.get("/sport/program/active")
    def get_active_sport_program(session: Session = Depends(get_session)) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        return sport_program_context(session, user.id)

    @app.get("/sport/progress")
    def get_sport_progress(session: Session = Depends(get_session)) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        return build_sport_progress(session, user.id)

    @app.post("/sport/today", status_code=status.HTTP_201_CREATED)
    def create_sport_today(
        payload: SportTodayRequest,
        response: Response,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        result = create_or_reuse_sport_today_workout(session, user.id, payload)
        response.status_code = status.HTTP_200_OK if result["reused"] else status.HTTP_201_CREATED
        return result

    @app.post("/sport/missed-day", status_code=status.HTTP_201_CREATED)
    def record_sport_missed_day(payload: SportMissedDayRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        return create_missed_day_adjustment(session, user.id, payload)

    @app.post("/checkins", status_code=status.HTTP_201_CREATED)
    def create_checkin(payload: CheckinCreate, session: Session = Depends(get_session)) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        area = ensure_area(session, user.id, payload.area)
        checkin = Checkin(
            user_id=user.id,
            area_id=area.id,
            mood=payload.mood,
            energy=payload.energy,
            stress=payload.stress,
            notes=payload.notes,
        )
        session.add(checkin)
        session.commit()
        session.refresh(checkin)
        checkin.area = area
        return checkin_to_dict(checkin)

    @app.post("/tasks", status_code=status.HTTP_201_CREATED)
    def create_task(payload: TaskCreate, session: Session = Depends(get_session)) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        area = ensure_area(session, user.id, payload.area)
        task = Task(
            user_id=user.id,
            area_id=area.id,
            title=payload.title,
            notes=payload.notes,
            priority=payload.priority,
            due_date=payload.due_date,
            status="todo",
        )
        session.add(task)
        session.commit()
        session.refresh(task)
        task.area = area
        return task_to_dict(task)

    @app.patch("/tasks/{task_id}")
    def update_task(task_id: int, payload: TaskUpdate, session: Session = Depends(get_session)) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        task = session.scalar(select(Task).where(Task.id == task_id, Task.user_id == user.id))
        if task is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")

        updates = payload.model_dump(exclude_unset=True)
        if "area" in updates and updates["area"] is not None:
            area = ensure_area(session, user.id, updates.pop("area"))
            task.area_id = area.id
            task.area = area
        for field, value in updates.items():
            setattr(task, field, value)
        if "status" in updates:
            task.completed_at = utc_now() if updates["status"] == "done" else None

        session.commit()
        session.refresh(task)
        return task_to_dict(task)

    @app.post("/habits/log", status_code=status.HTTP_201_CREATED)
    def log_habit(
        payload: HabitLogCreate,
        response: Response,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        habit_slug = slugify(payload.habit)
        habit = session.scalar(
            select(HabitDefinition).where(HabitDefinition.user_id == user.id, HabitDefinition.slug == habit_slug)
        )
        if habit is None:
            habit = HabitDefinition(user_id=user.id, slug=habit_slug, name=payload.habit.strip().title())
            session.add(habit)
            session.flush()

        log = session.scalar(select(HabitLog).where(HabitLog.habit_id == habit.id, HabitLog.log_date == payload.log_date))
        created = log is None
        if log is None:
            log = HabitLog(user_id=user.id, habit_id=habit.id, log_date=payload.log_date)
            session.add(log)
        log.value = payload.value
        log.notes = payload.notes
        session.commit()
        session.refresh(log)
        log.habit = habit
        response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return habit_log_to_dict(log)

    @app.post("/workouts/recommend")
    def recommend_workout(
        payload: WorkoutRecommendationRequest,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        response = build_workout_recommendation(payload)
        session.add(
            AdviceLog(
                user_id=user.id,
                advice_type="workout_recommendation",
                input_payload=payload.model_dump(mode="json"),
                output_payload=response,
            )
        )
        session.commit()
        return response

    @app.post("/workouts/log", status_code=status.HTTP_201_CREATED)
    def log_workout(payload: WorkoutLogCreate, session: Session = Depends(get_session)) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        workout = WorkoutSession(
            user_id=user.id,
            session_date=payload.session_date,
            workout_type=payload.workout_type,
            duration_minutes=payload.duration_minutes,
            intensity=payload.intensity,
            notes=payload.notes,
        )
        workout.exercises = [
            WorkoutExercise(**exercise.model_dump(exclude_none=True)) for exercise in payload.exercises
        ]
        session.add(workout)
        session.commit()
        session.refresh(workout)
        return workout_to_dict(workout)

    @app.post("/workouts/plan", status_code=status.HTTP_201_CREATED)
    def create_workout_plan(payload: WorkoutPlanCreate, session: Session = Depends(get_session)) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        profile = get_or_create_life_profile(session, user.id)
        location_context = payload.location_context or profile.default_context
        recommendation = build_planned_workout(
            goal=payload.goal,
            available_minutes=payload.available_minutes,
            equipment=payload.equipment,
            intensity=payload.intensity,
            location_context=location_context,
        )
        plan = PlannedWorkout(
            user_id=user.id,
            plan_date=payload.plan_date,
            status="proposed",
            location_context=location_context,
            goal=payload.goal,
            intensity=payload.intensity,
            duration_minutes=payload.available_minutes,
            equipment=payload.equipment,
            exercises=jsonable_encoder(recommendation["exercises"]),
            telegram_metadata=jsonable_encoder(payload.telegram_metadata),
            notes=payload.notes,
        )
        session.add(plan)
        session.flush()
        output = planned_workout_to_dict(plan)
        session.add(
            AdviceLog(
                user_id=user.id,
                advice_type="planned_workout",
                input_payload=payload.model_dump(mode="json"),
                output_payload=jsonable_encoder(output),
            )
        )
        session.commit()
        session.refresh(plan)
        return planned_workout_to_dict(plan)

    @app.get("/workouts/plans/{plan_id}")
    def get_workout_plan(plan_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        try:
            plan = get_planned_workout_or_404(session, user.id, plan_id)
        except PlannedWorkoutNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="planned workout not found") from exc
        return planned_workout_to_dict(plan)

    @app.patch("/workouts/plans/{plan_id}")
    def update_workout_plan(plan_id: int, payload: WorkoutPlanUpdate, session: Session = Depends(get_session)) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        try:
            plan = get_planned_workout_or_404(session, user.id, plan_id)
        except PlannedWorkoutNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="planned workout not found") from exc
        updates = payload.model_dump(exclude_unset=True)
        if "status" in updates and updates["status"] is not None:
            if updates["status"] not in PLANNED_WORKOUT_STATUSES:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid planned workout status")
            plan.status = updates["status"]
        if "notes" in updates:
            plan.notes = updates["notes"]
        session.commit()
        session.refresh(plan)
        return planned_workout_to_dict(plan)

    @app.post("/workouts/plans/{plan_id}/complete")
    def complete_workout_plan(
        plan_id: int,
        payload: WorkoutPlanComplete,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        try:
            plan = get_planned_workout_or_404(session, user.id, plan_id)
        except PlannedWorkoutNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="planned workout not found") from exc
        if plan.completed_workout_id is None:
            workout = WorkoutSession(
                user_id=user.id,
                session_date=plan.plan_date,
                workout_type=plan.goal,
                duration_minutes=plan.duration_minutes,
                intensity=plan.intensity,
                notes=payload.notes or plan.notes,
            )
            workout.exercises = [
                WorkoutExercise(**exercise_payload_from_plan(exercise)) for exercise in plan.exercises
            ]
            session.add(workout)
            session.flush()
            plan.completed_workout_id = workout.id
        if payload.notes:
            plan.notes = payload.notes
        plan.status = "completed"
        session.commit()
        session.refresh(plan)
        return planned_workout_to_dict(plan)

    @app.post("/health/daily-summaries", status_code=status.HTTP_201_CREATED)
    def upsert_health_daily_summary(
        payload: HealthDailySummaryUpsert,
        response: Response,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        summary, created = upsert_health_summary(payload, session)
        response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return health_daily_summary_to_dict(summary)

    @app.post("/integrations/shortcuts/health-daily-summary", status_code=status.HTTP_201_CREATED)
    def ingest_shortcut_health_daily_summary(
        payload: HealthDailySummaryUpsert,
        response: Response,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        summary, created = upsert_health_summary(payload, session)
        response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return health_daily_summary_to_dict(summary)

    @app.get("/food/target")
    def get_food_target(session: Session = Depends(get_session)) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        target = get_or_create_active_food_target(session, user.id)
        session.commit()
        session.refresh(target)
        return food_target_to_dict(target)

    @app.post("/food/target/recalculate", status_code=status.HTTP_201_CREATED)
    def recalculate_food_target(payload: FoodTargetRecalculate, session: Session = Depends(get_session)) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        effective_date = payload.effective_date or lifeos_today()
        target = create_food_target(
            session,
            user.id,
            effective_date,
            calories_override=payload.calories,
            protein_override=payload.protein_g,
            notes=payload.notes,
            archive_existing=True,
        )
        output = food_target_to_dict(target)
        session.add(
            AdviceLog(
                user_id=user.id,
                advice_type="food_target_recalculation",
                input_payload=payload.model_dump(mode="json"),
                output_payload=jsonable_encoder(output),
            )
        )
        session.commit()
        session.refresh(target)
        return food_target_to_dict(target)

    @app.post("/food/logs", status_code=status.HTTP_201_CREATED)
    def create_food_log(payload: FoodLogCreate, session: Session = Depends(get_session)) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        get_or_create_active_food_target(session, user.id, payload.log_date)
        food_log = FoodLog(
            user_id=user.id,
            log_date=payload.log_date,
            meal_type=slugify(payload.meal_type),
            status="active",
            source=payload.source,
            description=payload.description,
            calories=payload.calories,
            protein_g=payload.protein_g,
            carbs_g=payload.carbs_g,
            fat_g=payload.fat_g,
            confidence=payload.confidence,
            telegram_metadata=jsonable_encoder(payload.telegram_metadata),
            notes=payload.notes,
        )
        food_log.items = [food_log_item_from_payload(item) for item in payload.items]
        session.add(food_log)
        session.commit()
        session.refresh(food_log)
        return food_log_to_dict(food_log)

    @app.patch("/food/logs/{food_log_id}")
    def update_food_log(food_log_id: int, payload: FoodLogUpdate, session: Session = Depends(get_session)) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        try:
            food_log = get_food_log_or_404(session, user.id, food_log_id)
        except FoodLogNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="food log not found") from exc
        updates = payload.model_dump(exclude_unset=True)
        items = updates.pop("items", None)
        if "status" in updates and updates["status"] is not None and updates["status"] not in FOOD_LOG_STATUSES:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid food log status")
        if "meal_type" in updates and updates["meal_type"] is not None:
            updates["meal_type"] = slugify(updates["meal_type"])
        if "telegram_metadata" in updates and updates["telegram_metadata"] is not None:
            updates["telegram_metadata"] = jsonable_encoder(updates["telegram_metadata"])
        for field, value in updates.items():
            setattr(food_log, field, value)
        if items is not None:
            food_log.items = [food_log_item_from_payload(FoodLogItemPayload.model_validate(item)) for item in items]
        session.commit()
        session.refresh(food_log)
        return food_log_to_dict(food_log)

    @app.get("/food/daily-summary")
    def get_food_daily_summary(summary_date: date | None = None, session: Session = Depends(get_session)) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        effective_date = summary_date or lifeos_today()
        target = get_or_create_active_food_target(session, user.id, effective_date)
        session.commit()
        return build_food_daily_summary(session, user.id, effective_date, target)

    @app.get("/food/progress")
    def get_food_progress(reference_date: date | None = None, session: Session = Depends(get_session)) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        effective_date = reference_date or lifeos_today()
        target = get_or_create_active_food_target(session, user.id, effective_date)
        session.commit()
        return build_food_progress_context(session, user.id, effective_date, target)

    @app.post("/food/reviews/daily", status_code=status.HTTP_201_CREATED)
    def create_food_daily_review(payload: FoodDailyReviewCreate, session: Session = Depends(get_session)) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        review = session.scalar(select(FoodDailyReview).where(FoodDailyReview.user_id == user.id, FoodDailyReview.review_date == payload.review_date))
        if review is None:
            review = FoodDailyReview(user_id=user.id, review_date=payload.review_date)
            session.add(review)
        review.hunger = payload.hunger
        review.energy = payload.energy
        review.adherence_status = payload.adherence_status
        review.notes = payload.notes
        review.recommendations = payload.recommendations
        session.commit()
        session.refresh(review)
        return food_daily_review_to_dict(review)

    @app.post("/finance/import", status_code=status.HTTP_201_CREATED)
    def import_finance(payload: FinanceImportRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        rows, upload = rows_from_import_payload(payload)
        if upload is not None:
            maybe_store_upload(session, user.id, upload)

        import_hash = hashlib.sha256(
            json.dumps({"source": payload.source, "rows": rows}, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        existing_import = session.scalar(select(FinanceImport).where(FinanceImport.import_hash == import_hash))
        if existing_import is not None:
            return {
                "id": existing_import.id,
                "source": existing_import.source,
                "status": "duplicate",
                "staged": 0,
                "skipped": len(rows),
                "review_items": existing_import.review_items,
            }

        review_items = []
        for row_index, row in enumerate(rows):
            normalized = normalize_finance_row(row)
            normalized["row_index"] = row_index
            normalized["external_id"] = transaction_external_id(payload.source, import_hash, row_index, normalized)
            normalized["status"] = "pending"
            review_items.append(jsonable_encoder(normalized))

        import_record = FinanceImport(
            user_id=user.id,
            source=payload.source,
            import_hash=import_hash,
            status="review_pending",
            raw_rows=jsonable_encoder(rows),
            review_items=review_items,
        )
        session.add(import_record)
        session.commit()
        session.refresh(import_record)
        return finance_import_to_dict(import_record, staged=len(review_items), skipped=0)

    @app.post("/finance/import/{import_id}/approve")
    def approve_finance_import(
        import_id: int,
        payload: FinanceImportDecisionRequest,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        import_record = get_finance_import_or_404(session, user.id, import_id)
        selected = set(payload.row_indexes) if payload.row_indexes is not None else None
        review_items = list(import_record.review_items or [])
        imported = 0
        skipped = 0

        for item in review_items:
            row_index = int(item["row_index"])
            if selected is not None and row_index not in selected:
                continue
            if item.get("status") in {"approved", "rejected"}:
                skipped += 1
                continue
            existing = session.scalar(select(FinanceTransaction).where(FinanceTransaction.external_id == item["external_id"]))
            if existing is not None:
                item["status"] = "duplicate"
                skipped += 1
                continue

            account = get_or_create_account(session, user.id, item["account"], item["currency"])
            category = get_or_create_category(session, user.id, item["category"], float(item["amount"]))
            session.add(
                FinanceTransaction(
                    user_id=user.id,
                    account_id=account.id,
                    category_id=category.id,
                    import_id=import_record.id,
                    transaction_date=coerce_date(item["date"]),
                    description=item["description"],
                    amount=float(item["amount"]),
                    currency=item["currency"],
                    external_id=item["external_id"],
                )
            )
            item["status"] = "approved"
            imported += 1

        import_record.review_items = review_items
        flag_modified(import_record, "review_items")
        import_record.imported_count += imported
        import_record.status = finance_import_status(review_items)
        session.commit()
        session.refresh(import_record)
        return finance_import_to_dict(import_record, imported=imported, skipped=skipped)

    @app.post("/finance/import/{import_id}/reject")
    def reject_finance_import(
        import_id: int,
        payload: FinanceImportDecisionRequest,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        import_record = get_finance_import_or_404(session, user.id, import_id)
        selected = set(payload.row_indexes) if payload.row_indexes is not None else None
        review_items = list(import_record.review_items or [])
        rejected = 0
        for item in review_items:
            row_index = int(item["row_index"])
            if selected is not None and row_index not in selected:
                continue
            if item.get("status") == "pending":
                item["status"] = "rejected"
                rejected += 1
        import_record.review_items = review_items
        flag_modified(import_record, "review_items")
        import_record.status = finance_import_status(review_items)
        session.commit()
        session.refresh(import_record)
        return finance_import_to_dict(import_record, rejected=rejected)

    @app.get("/finance")
    def finance(session: Session = Depends(get_session)) -> dict[str, Any]:
        return finance_summary(session)

    @app.get("/finance/summary")
    def finance_summary(session: Session = Depends(get_session)) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        transactions = session.scalars(select(FinanceTransaction).where(FinanceTransaction.user_id == user.id)).all()
        income = money(sum(tx.amount for tx in transactions if tx.amount > 0))
        expenses = money(abs(sum(tx.amount for tx in transactions if tx.amount < 0)))
        net = money(income - expenses)

        category_rows = session.execute(
            select(FinanceCategory.name, func.sum(FinanceTransaction.amount))
            .join(FinanceTransaction, FinanceTransaction.category_id == FinanceCategory.id)
            .where(FinanceTransaction.user_id == user.id)
            .group_by(FinanceCategory.name)
            .order_by(FinanceCategory.name)
        ).all()
        accounts = session.scalars(select(FinanceAccount).where(FinanceAccount.user_id == user.id).order_by(FinanceAccount.name)).all()

        return {
            "income": income,
            "expenses": expenses,
            "net": net,
            "by_category": [{"category": name, "amount": money(amount or 0)} for name, amount in category_rows],
            "accounts": [
                {
                    "name": account.name,
                    "posted_balance": money(account.balance),
                    "currency": account.currency,
                    "balance_source": "manual_or_bank_reported",
                }
                for account in accounts
            ],
        }

    @app.post("/finance/affordability")
    def finance_affordability(payload: FinanceAffordabilityRequest) -> dict[str, Any]:
        remaining_needed = max(payload.purchase_amount - payload.current_savings, 0)
        monthly_savings_needed = money(remaining_needed / payload.months)
        monthly_surplus = money(payload.monthly_income - payload.monthly_expenses)
        projected_remaining = money((monthly_surplus * payload.months) + payload.current_savings - payload.purchase_amount)
        affordable = monthly_savings_needed <= monthly_surplus
        recommendation = (
            "Affordable within the requested timeline."
            if affordable
            else "Delay, reduce scope, or increase monthly surplus before buying."
        )
        return {
            "affordable": affordable,
            "monthly_savings_needed": monthly_savings_needed,
            "monthly_surplus": monthly_surplus,
            "projected_remaining": projected_remaining,
            "recommendation": recommendation,
        }

    @app.post("/daily/plan", status_code=status.HTTP_201_CREATED)
    def create_daily_plan(payload: DailyPlanRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        focus_area = ensure_area(session, user.id, payload.focus_area) if payload.focus_area else None

        task_query = select(Task).where(Task.user_id == user.id, Task.status != "done")
        if focus_area is not None:
            task_query = task_query.where(Task.area_id == focus_area.id)
        else:
            task_query = task_query.where(or_(Task.due_date.is_(None), Task.due_date <= payload.plan_date))
        tasks = session.scalars(task_query.order_by(Task.priority.desc(), Task.created_at).limit(5)).all()

        habit_query = select(HabitDefinition).where(HabitDefinition.user_id == user.id, HabitDefinition.is_active.is_(True))
        if focus_area is not None:
            habit_query = habit_query.where(HabitDefinition.area_id == focus_area.id)
        habits = session.scalars(habit_query.order_by(HabitDefinition.name).limit(5)).all()

        task_payload = jsonable_encoder([task_to_dict(task) for task in tasks])
        habit_payload = jsonable_encoder([habit_to_dict(habit) for habit in habits])
        recommendations = build_daily_recommendations(payload.capacity_minutes, task_payload, habit_payload)

        plan = session.scalar(select(DailyPlan).where(DailyPlan.user_id == user.id, DailyPlan.plan_date == payload.plan_date))
        if plan is None:
            plan = DailyPlan(user_id=user.id, plan_date=payload.plan_date)
            session.add(plan)
        plan.focus_area_id = focus_area.id if focus_area else None
        plan.capacity_minutes = payload.capacity_minutes
        plan.tasks = task_payload
        plan.habits = habit_payload
        plan.recommendations = recommendations

        session.flush()
        output = daily_plan_to_dict(plan, focus_area.slug if focus_area else None)
        session.add(
            AdviceLog(
                user_id=user.id,
                advice_type="daily_plan",
                input_payload=payload.model_dump(mode="json"),
                output_payload=jsonable_encoder(output),
            )
        )
        session.commit()
        session.refresh(plan)
        return output

    @app.post("/reviews/daily", status_code=status.HTTP_201_CREATED)
    def create_daily_review(payload: DailyReviewCreate, session: Session = Depends(get_session)) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        review = session.scalar(select(DailyReview).where(DailyReview.user_id == user.id, DailyReview.review_date == payload.review_date))
        if review is None:
            review = DailyReview(user_id=user.id, review_date=payload.review_date)
            session.add(review)
        review.wins = payload.wins
        review.blockers = payload.blockers
        review.mood = payload.mood
        review.energy = payload.energy
        review.notes = payload.notes
        session.commit()
        session.refresh(review)
        return daily_review_to_dict(review)

    @app.post("/reviews/weekly", status_code=status.HTTP_201_CREATED)
    def create_weekly_review(payload: WeeklyReviewCreate, session: Session = Depends(get_session)) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        review = session.scalar(select(WeeklyReview).where(WeeklyReview.user_id == user.id, WeeklyReview.week_start == payload.week_start))
        if review is None:
            review = WeeklyReview(user_id=user.id, week_start=payload.week_start)
            session.add(review)
        review.wins = payload.wins
        review.lessons = payload.lessons
        review.next_focus = payload.next_focus
        review.score = payload.score
        review.notes = payload.notes
        session.commit()
        session.refresh(review)
        return weekly_review_to_dict(review)

    return app


def get_or_create_life_profile(session: Session, user_id: int) -> LifeProfile:
    profile = session.scalar(select(LifeProfile).where(LifeProfile.user_id == user_id))
    if profile is None:
        profile = LifeProfile(user_id=user_id, **DEFAULT_PROFILE)
        session.add(profile)
        session.flush()
    return profile


def profile_settings(session: Session, user_id: int) -> dict[str, dict[str, Any]]:
    settings = session.scalars(select(ProfileSetting).where(ProfileSetting.user_id == user_id).order_by(ProfileSetting.domain)).all()
    return {setting.domain: setting.settings for setting in settings}


def get_or_create_profile_setting(session: Session, user_id: int, domain: str) -> ProfileSetting:
    setting = session.scalar(select(ProfileSetting).where(ProfileSetting.user_id == user_id, ProfileSetting.domain == domain))
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


def sport_program_context(session: Session, user_id: int, reference_date: date | None = None) -> dict[str, Any]:
    goal, program = get_active_sport_goal_and_program(session, user_id)
    effective_date = reference_date or lifeos_today()
    current_week = get_current_program_week(session, program, effective_date)
    health_summaries = recent_health_summaries(session, user_id)
    next_plan = session.scalar(
        select(PlannedWorkout)
        .where(
            PlannedWorkout.user_id == user_id,
            PlannedWorkout.program_id == program.id,
            PlannedWorkout.plan_date >= effective_date,
            PlannedWorkout.status.in_(["proposed", "accepted", "started"]),
        )
        .order_by(PlannedWorkout.plan_date.asc(), PlannedWorkout.created_at.desc())
        .limit(1)
    )
    return {
        "goal": sport_goal_to_dict(goal),
        "program": training_program_to_dict(program),
        "current_week": training_program_week_to_dict(current_week),
        "health_progress": build_health_progress(health_summaries),
        "weekly_adherence": weekly_adherence(session, user_id, current_week),
        "next_planned_workout": planned_workout_to_dict(next_plan) if next_plan else None,
    }


def build_sport_progress(session: Session, user_id: int, reference_date: date | None = None) -> dict[str, Any]:
    reference_date = reference_date or lifeos_today()
    goal, program = get_active_sport_goal_and_program(session, user_id)
    current_week = get_current_program_week(session, program, reference_date)
    health_summaries = recent_health_summaries(session, user_id)
    health_progress = build_health_progress(health_summaries)
    latest_metrics = (health_progress["latest"] or {}).get("metrics", {})
    latest_weight = latest_metrics.get("weight_kg")
    weight_days = health_progress["data_quality"]["metric_days_available"].get("weight_kg", 0)
    weekly = weekly_adherence(session, user_id, current_week)
    steps_average = health_progress["seven_day_average"].get("steps", 0)
    active_energy_average = health_progress["seven_day_average"].get("active_energy_kcal", 0)
    movement_rate = min(float(steps_average or 0) / current_week.target_steps_avg, 1) if current_week.target_steps_avg else 0

    if latest_weight is None:
        weight_score = 0
        weight_delta_from_target = None
    else:
        weight_delta_from_target = rounded_metric(float(latest_weight) - current_week.target_weight_kg)
        weight_score = max(0, min(40, 40 - max(float(weight_delta_from_target), 0) * 5))
    workout_score = min(weekly["completion_rate"], 1) * 30
    movement_score = movement_rate * 20
    recovery_score = 10 if weekly["skipped_sessions"] == 0 else max(0, 10 - weekly["skipped_sessions"] * 3)
    on_track_score = int(round(weight_score + workout_score + movement_score + recovery_score))

    summary_count = health_progress["data_quality"]["summary_count"]
    completed_sessions = weekly["completed_sessions"]
    latest_sync_date = health_progress["latest"]["summary_date"] if health_progress["latest"] else None
    recent_sync = bool(latest_sync_date and (reference_date - latest_sync_date).days <= 2)
    if latest_weight is not None and weight_days >= 7 and completed_sessions >= 2 and recent_sync:
        confidence = "high"
    elif latest_weight is not None and (weight_days >= 3 or completed_sessions >= 1 or recent_sync):
        confidence = "medium"
    else:
        confidence = "low"

    reasons = []
    if weight_days < 7:
        reasons.append("Weight trend confidence is low until at least 7 daily weight entries are synced.")
    if completed_sessions < 2:
        reasons.append("Workout adherence confidence is low until at least 2 program workouts are completed.")
    if not recent_sync:
        reasons.append("Movement confidence is low because no recent health sync is available.")
    if latest_weight is not None:
        reasons.append(f"Latest synced weight is {rounded_metric(float(latest_weight))} kg against this week's target of {current_week.target_weight_kg} kg.")

    stretch_required_weekly_loss = required_weekly_loss(goal.start_weight_kg, goal.stretch_weight_kg, goal.start_date, goal.stretch_date)
    healthy_pace_status = "aggressive" if stretch_required_weekly_loss > goal.healthy_weekly_loss_max_kg else "healthy_range"

    return {
        "goal": sport_goal_to_dict(goal),
        "program": training_program_to_dict(program),
        "current_week": training_program_week_to_dict(current_week),
        "latest_weight_kg": latest_weight,
        "target_weight_this_week_kg": current_week.target_weight_kg,
        "weight_delta_from_week_target_kg": weight_delta_from_target,
        "stretch": {
            "weight_kg": goal.stretch_weight_kg,
            "date": goal.stretch_date,
            "required_weekly_loss_kg": stretch_required_weekly_loss,
            "healthy_pace_status": healthy_pace_status,
        },
        "weekly_adherence": weekly,
        "movement_adherence": {
            "steps_average": steps_average,
            "active_energy_average": active_energy_average,
            "target_steps_avg": current_week.target_steps_avg,
            "completion_rate": rounded_metric(movement_rate),
        },
        "on_track_score": max(0, min(on_track_score, 100)),
        "confidence": confidence,
        "reasons": reasons,
        "next_actions": sport_next_actions(confidence, healthy_pace_status, weekly, movement_rate),
        "health_progress": health_progress,
    }


def create_or_reuse_sport_today_workout(
    session: Session,
    user_id: int,
    payload: SportTodayRequest,
) -> dict[str, Any]:
    request_date = payload.request_date or lifeos_today()
    goal, program = get_active_sport_goal_and_program(session, user_id)
    current_week = get_current_program_week(session, program, request_date)
    settings = profile_settings(session, user_id)
    sport_settings = settings.get("sport", {})
    existing = session.scalar(
        select(PlannedWorkout)
        .where(
            PlannedWorkout.user_id == user_id,
            PlannedWorkout.program_id == program.id,
            PlannedWorkout.plan_date == request_date,
            PlannedWorkout.status.in_(["proposed", "accepted", "started"]),
        )
        .order_by(PlannedWorkout.created_at.desc())
        .limit(1)
    )
    if existing is not None:
        return sport_today_response(existing, goal, program, current_week, reused=True)

    location_context = payload.location_context or infer_location_context(request_date, program, sport_settings)
    available_minutes = payload.available_minutes or personalized_default_minutes(location_context, sport_settings, current_week)
    intensity = intensity_for_week(current_week)
    program_day = max(1, min((request_date - current_week.week_start).days + 1, 7))
    focus = personalized_focus(request_date, location_context, current_week, program_day, sport_settings)
    weekly = weekly_adherence(session, user_id, current_week)
    if has_poor_sleep_signal(payload.notes):
        focus = "poor_sleep_recovery"
        intensity = "easy"
        available_minutes = min(available_minutes, 40)
    elif weekly["skipped_sessions"] > 0 or has_recent_missed_adjustment(session, program, request_date):
        focus = "recovery"
        intensity = "easy"
        available_minutes = min(available_minutes, 30)
    workout = build_planned_workout(
        goal="fat_loss",
        available_minutes=available_minutes,
        equipment=payload.equipment,
        intensity=intensity,
        location_context=location_context,
        focus=focus,
        sport_settings=sport_settings,
    )
    exercises = add_program_notes_to_exercises(workout["exercises"], current_week, program_day)
    plan = PlannedWorkout(
        user_id=user_id,
        plan_date=request_date,
        status="proposed",
        location_context=location_context,
        goal="fat_loss",
        intensity=intensity,
        duration_minutes=available_minutes,
        equipment=payload.equipment,
        exercises=jsonable_encoder(exercises),
        telegram_metadata={},
        notes=payload.notes or f"Program week {current_week.week_number}: {current_week.phase}",
        program_id=program.id,
        program_week_id=current_week.id,
        program_day=program_day,
        source="program",
        adaptation_reason=f"{current_week.phase}:{focus}",
    )
    session.add(plan)
    session.flush()
    output = sport_today_response(plan, goal, program, current_week, reused=False)
    session.add(
        AdviceLog(
            user_id=user_id,
            advice_type="sport_today",
            input_payload=payload.model_dump(mode="json"),
            output_payload=jsonable_encoder(output),
        )
    )
    session.commit()
    session.refresh(plan)
    return sport_today_response(plan, goal, program, current_week, reused=False)


def create_missed_day_adjustment(session: Session, user_id: int, payload: SportMissedDayRequest) -> dict[str, Any]:
    _, program = get_active_sport_goal_and_program(session, user_id)
    current_week = get_current_program_week(session, program, payload.missed_date)
    skipped_plan = session.scalar(
        select(PlannedWorkout)
        .where(
            PlannedWorkout.user_id == user_id,
            PlannedWorkout.program_id == program.id,
            PlannedWorkout.plan_date == payload.missed_date,
            PlannedWorkout.status.in_(["proposed", "accepted", "started"]),
        )
        .order_by(PlannedWorkout.created_at.desc())
        .limit(1)
    )
    if skipped_plan is not None:
        skipped_plan.status = "skipped"
        skipped_plan.notes = append_note(skipped_plan.notes, payload.notes or payload.reason or "Marked missed by OpenClue.")
    next_actions = [
        "Keep the next session easy instead of doubling intensity.",
        "Do 20-30 minutes of walking and mobility if today is still available.",
        "Resume the program schedule from the next planned day.",
    ]
    output_payload = {
        "week_number": current_week.week_number,
        "phase": current_week.phase,
        "next_actions": next_actions,
    }
    adjustment = ProgramAdjustment(
        program_id=program.id,
        adjustment_date=payload.missed_date,
        reason="missed_workout",
        input_payload=payload.model_dump(mode="json"),
        output_payload=output_payload,
        notes=payload.notes or payload.reason,
    )
    session.add(adjustment)
    session.commit()
    session.refresh(adjustment)
    return {
        "adjustment": program_adjustment_to_dict(adjustment),
        "current_week": training_program_week_to_dict(current_week),
        "skipped_plan": planned_workout_to_dict(skipped_plan) if skipped_plan else None,
        "next_actions": next_actions,
    }


def get_active_sport_goal_and_program(session: Session, user_id: int) -> tuple[SportGoal, TrainingProgram]:
    goal = session.scalar(
        select(SportGoal).where(SportGoal.user_id == user_id, SportGoal.status == "active").order_by(SportGoal.created_at.desc())
    )
    program = None
    if goal is not None:
        program = session.scalar(
            select(TrainingProgram).where(
                TrainingProgram.user_id == user_id,
                TrainingProgram.sport_goal_id == goal.id,
                TrainingProgram.status == "active",
            )
        )
    if goal is None or program is None:
        seed_sport_program(session, user_id)
        goal = session.scalar(
            select(SportGoal).where(SportGoal.user_id == user_id, SportGoal.status == "active").order_by(SportGoal.created_at.desc())
        )
        program = session.scalar(
            select(TrainingProgram).where(
                TrainingProgram.user_id == user_id,
                TrainingProgram.sport_goal_id == goal.id,
                TrainingProgram.status == "active",
            )
        )
    if goal is None or program is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="sport program seed failed")
    return goal, program


def get_current_program_week(
    session: Session,
    program: TrainingProgram,
    reference_date: date | None = None,
) -> TrainingProgramWeek:
    reference_date = reference_date or lifeos_today()
    elapsed_days = max((reference_date - program.start_date).days, 0)
    week_number = min((elapsed_days // 7) + 1, program.duration_weeks)
    if program.current_week_number != week_number:
        program.current_week_number = week_number
        session.flush()
    week = session.scalar(
        select(TrainingProgramWeek).where(
            TrainingProgramWeek.program_id == program.id,
            TrainingProgramWeek.week_number == week_number,
        )
    )
    if week is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="current sport program week missing")
    return week


def recent_health_summaries(session: Session, user_id: int, limit: int = 14) -> list[HealthDailySummary]:
    return list(
        session.scalars(
            select(HealthDailySummary)
            .where(HealthDailySummary.user_id == user_id)
            .order_by(HealthDailySummary.summary_date.desc(), HealthDailySummary.updated_at.desc())
            .limit(limit)
        ).all()
    )


def weekly_adherence(session: Session, user_id: int, week: TrainingProgramWeek) -> dict[str, Any]:
    workouts = session.scalars(
        select(PlannedWorkout).where(
            PlannedWorkout.user_id == user_id,
            PlannedWorkout.program_week_id == week.id,
        )
    ).all()
    completed = [workout for workout in workouts if workout.status == "completed"]
    skipped = [workout for workout in workouts if workout.status == "skipped"]
    missed_adjustments = session.scalars(
        select(ProgramAdjustment).where(
            ProgramAdjustment.program_id == week.program_id,
            ProgramAdjustment.reason == "missed_workout",
            ProgramAdjustment.adjustment_date >= week.week_start,
            ProgramAdjustment.adjustment_date <= week.week_end,
        )
    ).all()
    skipped_dates = {workout.plan_date for workout in skipped} | {adjustment.adjustment_date for adjustment in missed_adjustments}
    target_sessions = week.target_strength_sessions + week.target_cardio_sessions
    completion_rate = round(len(completed) / target_sessions, 2) if target_sessions else 0
    return {
        "target_sessions": target_sessions,
        "completed_sessions": len(completed),
        "skipped_sessions": len(skipped_dates),
        "completion_rate": min(completion_rate, 1),
    }


def required_weekly_loss(
    start_weight: float,
    target_weight: float | None,
    start_date: date,
    target_date: date | None,
) -> float | None:
    if target_weight is None or target_date is None or target_date <= start_date:
        return None
    weeks = max((target_date - start_date).days / 7, 1)
    return rounded_metric((start_weight - target_weight) / weeks)


def sport_next_actions(confidence: str, healthy_pace_status: str, weekly: dict[str, Any], movement_rate: float) -> list[str]:
    actions = []
    if healthy_pace_status == "aggressive":
        actions.append("Treat the August weight target as a stretch milestone; do not use punishing workouts to chase it.")
    if weekly["completed_sessions"] == 0:
        actions.append("Complete the next easy program workout before adding intensity.")
    if movement_rate < 0.75:
        actions.append("Prioritize walking minutes today because movement adherence is below target.")
    if confidence == "low":
        actions.append("Keep syncing weight and activity daily so the trend becomes reliable.")
    return actions or ["Keep the scheduled workout and maintain the current pace."]


def infer_location_context(request_date: date, program: TrainingProgram, sport_settings: dict[str, Any]) -> str:
    weekday = request_date.strftime("%A").lower()
    if weekday in sport_settings.get("city_training_days", []):
        return "chisinau_pool" if weekday in {"wednesday", "saturday"} else "chisinau_gym"
    return program.default_location_context


def personalized_default_minutes(
    location_context: str,
    sport_settings: dict[str, Any],
    week: TrainingProgramWeek,
) -> int:
    session_minutes = sport_settings.get("session_minutes", {})
    normalized_location = slugify(location_context).replace("-", "_")
    if normalized_location in {"chisinau_pool", "pool", "swimming", "chisinau_gym", "gym", "chisinau_city"}:
        return int(session_minutes.get("city", default_minutes_for_week(week)))
    if normalized_location in {"grandparents_home", "home"}:
        return int(session_minutes.get("home", default_minutes_for_week(week)))
    return default_minutes_for_week(week)


def personalized_focus(
    request_date: date,
    location_context: str,
    week: TrainingProgramWeek,
    program_day: int,
    sport_settings: dict[str, Any],
) -> str:
    normalized_location = slugify(location_context).replace("-", "_")
    weekday = request_date.strftime("%A").lower()
    if normalized_location in {"chisinau_pool", "pool", "swimming"}:
        return "swim_low_impact"
    if normalized_location in {"chisinau_gym", "gym"}:
        return "gym_full_body"
    if normalized_location in {"grandparents_home", "home"}:
        if weekday == "thursday":
            return "home_midday_bodyweight"
        if sport_settings.get("home_training_time") == "midday":
            return "home_midday_bodyweight"
    return program_focus_for_day(week, program_day)


def has_poor_sleep_signal(notes: str | None) -> bool:
    if not notes:
        return False
    normalized = notes.lower()
    return any(signal in normalized for signal in ["poor sleep", "slept 4", "slept 5", "tired", "exhausted", "bad sleep"])


def program_focus_for_day(week: TrainingProgramWeek, program_day: int) -> str:
    days = week.plan_json.get("days", []) if isinstance(week.plan_json, dict) else []
    for day_plan in days:
        if day_plan.get("day") == program_day:
            return str(day_plan.get("focus") or "easy_cardio")
    return "easy_cardio"


def has_recent_missed_adjustment(session: Session, program: TrainingProgram, reference_date: date) -> bool:
    adjustment = session.scalar(
        select(ProgramAdjustment)
        .where(
            ProgramAdjustment.program_id == program.id,
            ProgramAdjustment.reason == "missed_workout",
            ProgramAdjustment.adjustment_date >= reference_date - timedelta(days=2),
            ProgramAdjustment.adjustment_date < reference_date,
        )
        .order_by(ProgramAdjustment.adjustment_date.desc())
        .limit(1)
    )
    return adjustment is not None


def append_note(existing: str | None, note: str) -> str:
    return f"{existing}\n{note}" if existing else note


def default_minutes_for_week(week: TrainingProgramWeek) -> int:
    if week.week_number <= 4:
        return 30
    if week.week_number <= 12:
        return 40
    return 45


def intensity_for_week(week: TrainingProgramWeek) -> str:
    return "easy" if week.week_number <= 4 else "moderate"


def add_program_notes_to_exercises(
    exercises: list[dict[str, Any]],
    week: TrainingProgramWeek,
    program_day: int,
) -> list[dict[str, Any]]:
    annotated = []
    for exercise in exercises:
        item = dict(exercise)
        note = item.get("notes")
        program_note = f"Program week {week.week_number}, day {program_day}; phase {week.phase}."
        item["notes"] = f"{note} {program_note}" if note else program_note
        annotated.append(item)
    return annotated


def sport_today_response(
    plan: PlannedWorkout,
    goal: SportGoal,
    program: TrainingProgram,
    current_week: TrainingProgramWeek,
    *,
    reused: bool,
) -> dict[str, Any]:
    return {
        "reused": reused,
        "goal": sport_goal_to_dict(goal),
        "program": training_program_to_dict(program),
        "current_week": training_program_week_to_dict(current_week),
        "planned_workout": planned_workout_to_dict(plan),
        "program_reason": f"Week {current_week.week_number} focuses on {current_week.phase}.",
    }


def rows_from_import_payload(payload: FinanceImportRequest) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if payload.rows is not None:
        if len(payload.rows) > 1000:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="too many finance rows")
        return payload.rows, None
    if not payload.content_base64 or not payload.file_name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="rows or file content is required")

    try:
        raw = base64.b64decode(payload.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid base64 file content") from exc
    if len(raw) > 5_000_000:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="finance import file is too large")
    suffix = payload.file_name.lower().rsplit(".", 1)[-1]
    buffer = io.BytesIO(raw)
    try:
        if suffix == "xlsx":
            frame = pd.read_excel(buffer)
        elif suffix == "csv":
            frame = pd.read_csv(buffer)
        elif suffix == "xls":
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="xls imports are not supported; export xlsx or csv")
        else:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="unsupported finance import file type")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="could not parse finance import file") from exc
    rows = frame.to_dict(orient="records")
    if len(rows) > 1000:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="too many finance rows")
    upload = {
        "file_name": payload.file_name,
        "content_type": payload.content_type,
        "byte_size": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    return rows, upload


def maybe_store_upload(session: Session, user_id: int, upload: dict[str, Any]) -> None:
    existing = session.scalar(select(UploadedFile).where(UploadedFile.sha256 == upload["sha256"]))
    if existing is None:
        session.add(UploadedFile(user_id=user_id, **upload))


def normalize_finance_row(row: dict[str, Any]) -> dict[str, Any]:
    raw_date = row.get("date") or row.get("transaction_date")
    raw_amount = row.get("amount")
    if raw_date is None or raw_amount is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="finance rows need date and amount")
    tx_date = coerce_date(raw_date)
    amount = coerce_amount(raw_amount)
    return {
        "date": tx_date,
        "description": str(row.get("description") or row.get("name") or "Transaction").strip(),
        "amount": amount,
        "category": slugify(str(row.get("category") or ("income" if amount >= 0 else "uncategorized"))),
        "account": slugify(str(row.get("account") or "checking")),
        "currency": str(row.get("currency") or "USD").upper()[:3],
        "transaction_id": str(row.get("transaction_id") or row.get("id") or row.get("reference") or "").strip() or None,
    }


def coerce_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    if hasattr(value, "date"):
        return value.date()
    return date.fromisoformat(str(value)[:10])


def coerce_amount(value: Any) -> float:
    if isinstance(value, int | float):
        return float(value)
    text_value = str(value).strip().replace("$", "").replace(",", "")
    if text_value.startswith("(") and text_value.endswith(")"):
        text_value = f"-{text_value[1:-1]}"
    return float(text_value)


def transaction_external_id(source: str, import_hash: str, row_index: int, normalized: dict[str, Any]) -> str:
    if normalized.get("transaction_id"):
        raw = "|".join([source, "bank-id", str(normalized["transaction_id"]), normalized["account"]])
    else:
        raw = "|".join([source, import_hash, str(row_index)])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_or_create_account(session: Session, user_id: int, account_name: str, currency: str = "USD") -> FinanceAccount:
    account = session.scalar(select(FinanceAccount).where(FinanceAccount.user_id == user_id, FinanceAccount.name == account_name))
    if account is None:
        account = FinanceAccount(user_id=user_id, name=account_name, currency=currency)
        session.add(account)
        session.flush()
    return account


def get_or_create_category(session: Session, user_id: int, category_slug: str, amount: float) -> FinanceCategory:
    category = session.scalar(
        select(FinanceCategory).where(FinanceCategory.user_id == user_id, FinanceCategory.slug == category_slug)
    )
    if category is None:
        category = FinanceCategory(
            user_id=user_id,
            slug=category_slug,
            name=category_slug.replace("-", " ").title(),
            kind="income" if amount >= 0 else "expense",
        )
        session.add(category)
        session.flush()
    return category


def build_daily_recommendations(capacity_minutes: int, tasks: list[dict[str, Any]], habits: list[dict[str, Any]]) -> list[str]:
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


def get_finance_import_or_404(session: Session, user_id: int, import_id: int) -> FinanceImport:
    import_record = session.scalar(select(FinanceImport).where(FinanceImport.id == import_id, FinanceImport.user_id == user_id))
    if import_record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="finance import not found")
    return import_record


def finance_import_status(review_items: list[dict[str, Any]]) -> str:
    statuses = {item.get("status") for item in review_items}
    if statuses <= {"approved", "duplicate"}:
        return "complete"
    if statuses <= {"rejected"}:
        return "rejected"
    return "review_pending"
