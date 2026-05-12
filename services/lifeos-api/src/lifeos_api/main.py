from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.attributes import flag_modified

from lifeos_api.api.deps import get_session
from lifeos_api.core.security import require_api_key
from lifeos_api.core.time import lifeos_today
from lifeos_api.database import create_engine_and_session, get_database_url, init_database
from lifeos_api.domain.daily import build_daily_recommendations
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
from lifeos_api.domain.finance import (
    FinanceError,
    coerce_date,
    finance_import_status,
    get_finance_import_or_404,
    get_or_create_account,
    get_or_create_category,
    maybe_store_upload,
    normalize_finance_row,
    rows_from_import_payload,
    transaction_external_id,
)
from lifeos_api.domain.health import build_health_progress, upsert_health_summary
from lifeos_api.domain.profile import (
    context_personalization,
    deep_merge_settings,
    get_or_create_life_profile,
    get_or_create_profile_setting,
    profile_settings,
)
from lifeos_api.domain.sport import (
    SportProgramError,
    build_sport_progress,
    create_missed_day_adjustment,
    create_or_reuse_sport_today_workout,
    sport_program_context,
)
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
    PlannedWorkout,
    Task,
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
    task_to_dict,
    weekly_review_to_dict,
    workout_to_dict,
)
from lifeos_api.seed import ensure_area, get_or_create_user, seed_reset_plan, seed_sport_program
from lifeos_api.utils import money, slugify


def sport_program_http_exception(exc: SportProgramError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=exc.detail)


def finance_http_exception(exc: FinanceError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


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
        try:
            return sport_program_context(session, user.id)
        except SportProgramError as exc:
            raise sport_program_http_exception(exc) from exc

    @app.get("/sport/program/active")
    def get_active_sport_program(session: Session = Depends(get_session)) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        try:
            return sport_program_context(session, user.id)
        except SportProgramError as exc:
            raise sport_program_http_exception(exc) from exc

    @app.get("/sport/progress")
    def get_sport_progress(session: Session = Depends(get_session)) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        try:
            return build_sport_progress(session, user.id)
        except SportProgramError as exc:
            raise sport_program_http_exception(exc) from exc

    @app.post("/sport/today", status_code=status.HTTP_201_CREATED)
    def create_sport_today(
        payload: SportTodayRequest,
        response: Response,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        sport_settings = profile_settings(session, user.id).get("sport", {})
        try:
            result = create_or_reuse_sport_today_workout(session, user.id, payload, sport_settings=sport_settings)
        except SportProgramError as exc:
            raise sport_program_http_exception(exc) from exc
        response.status_code = status.HTTP_200_OK if result["reused"] else status.HTTP_201_CREATED
        return result

    @app.post("/sport/missed-day", status_code=status.HTTP_201_CREATED)
    def record_sport_missed_day(payload: SportMissedDayRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        try:
            return create_missed_day_adjustment(session, user.id, payload)
        except SportProgramError as exc:
            raise sport_program_http_exception(exc) from exc

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
        try:
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
        except FinanceError as exc:
            raise finance_http_exception(exc) from exc

    @app.post("/finance/import/{import_id}/approve")
    def approve_finance_import(
        import_id: int,
        payload: FinanceImportDecisionRequest,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        try:
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
        except FinanceError as exc:
            raise finance_http_exception(exc) from exc

    @app.post("/finance/import/{import_id}/reject")
    def reject_finance_import(
        import_id: int,
        payload: FinanceImportDecisionRequest,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        try:
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
        except FinanceError as exc:
            raise finance_http_exception(exc) from exc

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
