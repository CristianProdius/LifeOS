from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import io
import json
import os
from collections.abc import Iterator
from datetime import date
from typing import Any

import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.attributes import flag_modified

from lifeos_api.database import create_engine_and_session, get_database_url, init_database
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
    HabitDefinition,
    HabitLog,
    HealthDailySummary,
    LifeProfile,
    PlannedWorkout,
    Task,
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
    HabitLogCreate,
    HealthDailySummaryUpsert,
    HealthResponse,
    LifeProfileUpdate,
    TaskCreate,
    TaskUpdate,
    WeeklyReviewCreate,
    WorkoutLogCreate,
    WorkoutPlanComplete,
    WorkoutPlanCreate,
    WorkoutPlanUpdate,
    WorkoutRecommendationRequest,
)
from lifeos_api.seed import ensure_area, get_or_create_user, seed_reset_plan
from lifeos_api.utils import money, slugify


DEFAULT_PROFILE = {
    "timezone": "Europe/Chisinau",
    "default_context": "grandparents_home",
    "training_level": "beginner_returning",
    "goals": ["fat_loss", "consistency", "run_later"],
    "equipment": {"walking_pad": "planned", "pull_up_bar": "planned"},
}

PLANNED_WORKOUT_STATUSES = {"proposed", "accepted", "started", "completed", "skipped", "replaced"}
HEALTH_PROGRESS_METRICS = (
    "steps",
    "active_energy_kcal",
    "weight_kg",
    "body_fat_percent",
    "bmi",
    "resting_heart_rate",
    "average_heart_rate",
)


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

    def get_session() -> Iterator[Session]:
        with session_factory() as session:
            yield session

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
        return profile_to_dict(profile)

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
        if normalized_area_slug in {"sport", "daily", "food"}:
            health_summaries = session.scalars(
                select(HealthDailySummary)
                .where(HealthDailySummary.user_id == user.id)
                .order_by(HealthDailySummary.summary_date.desc(), HealthDailySummary.updated_at.desc())
                .limit(7)
            ).all()
            context["profile"] = profile_to_dict(get_or_create_life_profile(session, user.id))
            context["recent_health_summaries"] = [health_daily_summary_to_dict(summary) for summary in health_summaries]
            context["health_progress"] = build_health_progress(health_summaries)
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
        plan = get_planned_workout_or_404(session, user.id, plan_id)
        return planned_workout_to_dict(plan)

    @app.patch("/workouts/plans/{plan_id}")
    def update_workout_plan(plan_id: int, payload: WorkoutPlanUpdate, session: Session = Depends(get_session)) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        plan = get_planned_workout_or_404(session, user.id, plan_id)
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
        plan = get_planned_workout_or_404(session, user.id, plan_id)
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
        return upsert_health_summary(payload, response, session)

    @app.post("/integrations/shortcuts/health-daily-summary", status_code=status.HTTP_201_CREATED)
    def ingest_shortcut_health_daily_summary(
        payload: HealthDailySummaryUpsert,
        response: Response,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        return upsert_health_summary(payload, response, session)

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


async def require_api_key(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_shortcut_token: str | None = Header(default=None, alias="X-Shortcut-Token"),
) -> None:
    if request.url.path.startswith("/integrations/shortcuts/"):
        require_shortcut_token(authorization=authorization, x_shortcut_token=x_shortcut_token)
        return

    expected = os.getenv("LIFEOS_API_KEY")
    allow_anonymous = os.getenv("LIFEOS_ALLOW_ANONYMOUS", "").lower() in {"1", "true", "yes"}
    if not expected and not allow_anonymous:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="api key is not configured")
    if expected and not hmac.compare_digest(x_api_key or "", expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid API key")


def require_shortcut_token(*, authorization: str | None, x_shortcut_token: str | None) -> None:
    expected = os.getenv("LIFEOS_SHORTCUT_TOKEN")
    if not expected:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="shortcut token is not configured")

    supplied = x_shortcut_token or bearer_token(authorization)
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid shortcut token")


def bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, separator, token = authorization.partition(" ")
    if separator and scheme.lower() == "bearer" and token.strip():
        return token.strip()
    return None


def upsert_health_summary(payload: HealthDailySummaryUpsert, response: Response, session: Session) -> dict[str, Any]:
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
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return health_daily_summary_to_dict(summary)


def get_or_create_life_profile(session: Session, user_id: int) -> LifeProfile:
    profile = session.scalar(select(LifeProfile).where(LifeProfile.user_id == user_id))
    if profile is None:
        profile = LifeProfile(user_id=user_id, **DEFAULT_PROFILE)
        session.add(profile)
        session.flush()
    return profile


def profile_to_dict(profile: LifeProfile) -> dict[str, Any]:
    return {
        "id": profile.id,
        "timezone": profile.timezone,
        "default_context": profile.default_context,
        "training_level": profile.training_level,
        "goals": profile.goals,
        "equipment": profile.equipment,
    }


def area_to_dict(area: Area) -> dict[str, Any]:
    return {"id": area.id, "slug": area.slug, "name": area.name, "description": area.description}


def task_to_dict(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "title": task.title,
        "area": task.area.slug if task.area else None,
        "status": task.status,
        "priority": task.priority,
        "due_date": task.due_date,
        "notes": task.notes,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def habit_to_dict(habit: HabitDefinition) -> dict[str, Any]:
    return {
        "id": habit.id,
        "slug": habit.slug,
        "name": habit.name,
        "target_value": habit.target_value,
        "unit": habit.unit,
        "frequency": habit.frequency,
    }


def habit_log_to_dict(log: HabitLog) -> dict[str, Any]:
    return {
        "id": log.id,
        "habit": log.habit.slug,
        "log_date": log.log_date,
        "value": log.value,
        "notes": log.notes,
    }


def checkin_to_dict(checkin: Checkin) -> dict[str, Any]:
    return {
        "id": checkin.id,
        "area": checkin.area.slug if checkin.area else None,
        "mood": checkin.mood,
        "energy": checkin.energy,
        "stress": checkin.stress,
        "notes": checkin.notes,
        "created_at": checkin.created_at,
    }


def workout_to_dict(workout: WorkoutSession) -> dict[str, Any]:
    return {
        "id": workout.id,
        "session_date": workout.session_date,
        "workout_type": workout.workout_type,
        "duration_minutes": workout.duration_minutes,
        "intensity": workout.intensity,
        "notes": workout.notes,
        "exercises": [
            {
                "id": exercise.id,
                "name": exercise.name,
                "sets": exercise.sets,
                "reps": exercise.reps,
                "weight": exercise.weight,
                "duration_seconds": exercise.duration_seconds,
                "notes": exercise.notes,
            }
            for exercise in workout.exercises
        ],
    }


def planned_workout_to_dict(plan: PlannedWorkout) -> dict[str, Any]:
    return {
        "id": plan.id,
        "plan_date": plan.plan_date,
        "status": plan.status,
        "location_context": plan.location_context,
        "goal": plan.goal,
        "intensity": plan.intensity,
        "duration_minutes": plan.duration_minutes,
        "equipment": plan.equipment,
        "exercises": plan.exercises,
        "telegram_metadata": plan.telegram_metadata,
        "notes": plan.notes,
        "completed_workout_id": plan.completed_workout_id,
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
    }


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
            "has_latest": has_latest,
            "has_trend": has_trend,
            "trend_status": "available" if has_trend else "needs_more_data" if has_latest else "no_data",
            "missing_latest_metrics": missing_latest_metrics,
        },
    }


def health_progress_summary_to_dict(summary: HealthDailySummary) -> dict[str, Any]:
    return {
        "id": summary.id,
        "summary_date": summary.summary_date,
        "source": summary.source,
        "metrics": health_metric_values(summary),
        "updated_at": summary.updated_at,
    }


def health_metric_values(summary: HealthDailySummary | None) -> dict[str, Any]:
    if summary is None:
        return {metric: None for metric in HEALTH_PROGRESS_METRICS}
    return {metric: getattr(summary, metric) for metric in HEALTH_PROGRESS_METRICS}


def rounded_metric(value: float) -> float | int:
    rounded = round(value, 2)
    return int(rounded) if rounded.is_integer() else rounded


def build_workout_recommendation(payload: WorkoutRecommendationRequest) -> dict[str, Any]:
    equipment = {item.lower() for item in payload.equipment}
    goal = payload.goal.lower()
    if "strength" in goal:
        exercises = [
            {"name": "Squat pattern", "sets": 3, "reps": 10, "notes": "Use dumbbells if available."},
            {"name": "Hinge pattern", "sets": 3, "reps": 10, "notes": "Keep reps controlled."},
            {"name": "Push pattern", "sets": 3, "reps": 8, "notes": "Stop two reps before failure."},
            {"name": "Pull pattern", "sets": 3, "reps": 12, "notes": "Use dumbbells" if "dumbbells" in equipment else "Use bodyweight rows."},
        ]
    elif "cardio" in goal:
        exercises = [
            {"name": "Warmup walk", "duration_seconds": 300},
            {"name": "Interval block", "duration_seconds": max((payload.available_minutes - 10) * 60, 300)},
            {"name": "Cooldown", "duration_seconds": 300},
        ]
    else:
        exercises = [
            {"name": "Mobility flow", "duration_seconds": 480},
            {"name": "Easy conditioning", "duration_seconds": max((payload.available_minutes - 12) * 60, 600)},
            {"name": "Breathing downshift", "duration_seconds": 240},
        ]

    return {
        "goal": payload.goal,
        "available_minutes": payload.available_minutes,
        "intensity": payload.intensity,
        "equipment": payload.equipment,
        "exercises": exercises,
    }


def build_planned_workout(
    *,
    goal: str,
    available_minutes: int,
    equipment: list[str],
    intensity: str,
    location_context: str,
) -> dict[str, Any]:
    normalized_location = slugify(location_context).replace("-", "_")
    equipment_set = {slugify(item).replace("-", "_") for item in equipment}
    if normalized_location in {"grandparents_home", "home"}:
        exercises = [
            {"name": "Easy walk", "duration_seconds": min(available_minutes, 20) * 60, "notes": "Nose-breathing pace if possible."},
            {"name": "Mobility flow", "duration_seconds": 360, "notes": "Hips, ankles, thoracic spine, shoulders."},
            {"name": "Chair squats", "sets": 2, "reps": 8, "notes": "Stop if knees hurt."},
            {"name": "Wall push-ups", "sets": 2, "reps": 8, "notes": "Keep it easy and controlled."},
            {"name": "Breathing downshift", "duration_seconds": 180},
        ]
    elif normalized_location in {"chisinau_pool", "pool", "swimming"}:
        exercises = [
            {"name": "Easy swim warm-up", "duration_seconds": 600},
            {"name": "Technique laps", "duration_seconds": max((available_minutes - 20) * 60, 600), "notes": "Easy effort, long rests."},
            {"name": "Pool cooldown", "duration_seconds": 300},
        ]
    elif normalized_location in {"chisinau_gym", "gym"} or equipment_set:
        exercises = [
            {"name": "Treadmill walk", "duration_seconds": 480, "notes": "Warm up at easy pace."},
            {"name": "Leg press", "sets": 2, "reps": 10, "notes": "RPE 6-7, controlled depth."},
            {"name": "Chest press", "sets": 2, "reps": 10},
            {"name": "Lat pulldown", "sets": 2, "reps": 10},
            {"name": "Stationary bike", "duration_seconds": max((available_minutes - 25) * 60, 300), "notes": "Zone 2 finish."},
        ]
    else:
        exercises = [
            {"name": "Easy walk", "duration_seconds": max((available_minutes - 8) * 60, 600)},
            {"name": "Mobility flow", "duration_seconds": 300},
            {"name": "Breathing downshift", "duration_seconds": 180},
        ]

    return {
        "goal": goal,
        "available_minutes": available_minutes,
        "intensity": intensity,
        "location_context": location_context,
        "equipment": equipment,
        "exercises": exercises,
    }


def exercise_payload_from_plan(exercise: dict[str, Any]) -> dict[str, Any]:
    allowed = {"name", "sets", "reps", "weight", "duration_seconds", "notes"}
    return {key: value for key, value in exercise.items() if key in allowed and value is not None}


def get_planned_workout_or_404(session: Session, user_id: int, plan_id: int) -> PlannedWorkout:
    plan = session.scalar(select(PlannedWorkout).where(PlannedWorkout.id == plan_id, PlannedWorkout.user_id == user_id))
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="planned workout not found")
    return plan


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


def daily_plan_to_dict(plan: DailyPlan, focus_area: str | None) -> dict[str, Any]:
    return {
        "id": plan.id,
        "plan_date": plan.plan_date,
        "focus_area": focus_area,
        "capacity_minutes": plan.capacity_minutes,
        "tasks": plan.tasks,
        "habits": plan.habits,
        "recommendations": plan.recommendations,
    }


def daily_review_to_dict(review: DailyReview) -> dict[str, Any]:
    return {
        "id": review.id,
        "review_date": review.review_date,
        "wins": review.wins,
        "blockers": review.blockers,
        "mood": review.mood,
        "energy": review.energy,
        "notes": review.notes,
    }


def weekly_review_to_dict(review: WeeklyReview) -> dict[str, Any]:
    return {
        "id": review.id,
        "week_start": review.week_start,
        "wins": review.wins,
        "lessons": review.lessons,
        "next_focus": review.next_focus,
        "score": review.score,
        "notes": review.notes,
    }


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


def finance_import_to_dict(
    import_record: FinanceImport,
    *,
    staged: int | None = None,
    imported: int = 0,
    skipped: int = 0,
    rejected: int = 0,
) -> dict[str, Any]:
    review_items = import_record.review_items or []
    return {
        "id": import_record.id,
        "source": import_record.source,
        "status": import_record.status,
        "staged": len(review_items) if staged is None else staged,
        "imported": imported,
        "imported_total": import_record.imported_count,
        "skipped": skipped,
        "rejected": rejected,
        "review_items": review_items,
    }
