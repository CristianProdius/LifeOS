from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import os
from collections.abc import Iterator
from datetime import date
from typing import Any

import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
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
    HealthResponse,
    TaskCreate,
    TaskUpdate,
    WeeklyReviewCreate,
    WorkoutLogCreate,
    WorkoutRecommendationRequest,
)
from lifeos_api.seed import ensure_area, get_or_create_user, seed_reset_plan
from lifeos_api.utils import money, slugify


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

    @app.get("/context/{area_slug}")
    def get_context(area_slug: str, session: Session = Depends(get_session)) -> dict[str, Any]:
        user, _ = get_or_create_user(session)
        area = session.scalar(select(Area).where(Area.user_id == user.id, Area.slug == slugify(area_slug)))
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

        return {
            "area": area_to_dict(area),
            "tasks": [task_to_dict(task) for task in tasks],
            "habits": [habit_to_dict(habit) for habit in habits],
            "recent_checkins": [checkin_to_dict(checkin) for checkin in checkins],
        }

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


async def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    expected = os.getenv("LIFEOS_API_KEY")
    allow_anonymous = os.getenv("LIFEOS_ALLOW_ANONYMOUS", "").lower() in {"1", "true", "yes"}
    if not expected and not allow_anonymous:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="api key is not configured")
    if expected and x_api_key != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid API key")


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
