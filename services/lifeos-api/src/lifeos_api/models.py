from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    timezone: Mapped[str] = mapped_column(String(80), default="UTC", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    areas: Mapped[list[Area]] = relationship(back_populates="user")


class LifeProfile(TimestampMixin, Base):
    __tablename__ = "life_profiles"
    __table_args__ = (UniqueConstraint("user_id", name="uq_life_profiles_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    timezone: Mapped[str] = mapped_column(String(80), default="Europe/Chisinau", nullable=False)
    default_context: Mapped[str] = mapped_column(String(80), default="grandparents_home", nullable=False)
    training_level: Mapped[str] = mapped_column(String(80), default="beginner_returning", nullable=False)
    goals: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    equipment: Mapped[dict[str, str]] = mapped_column(JSON, default=dict, nullable=False)


class Area(TimestampMixin, Base):
    __tablename__ = "areas"
    __table_args__ = (UniqueConstraint("user_id", "slug", name="uq_areas_user_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    user: Mapped[User] = relationship(back_populates="areas")
    tasks: Mapped[list[Task]] = relationship(back_populates="area")
    task_templates: Mapped[list[TaskTemplate]] = relationship(back_populates="area")
    habit_definitions: Mapped[list[HabitDefinition]] = relationship(back_populates="area")
    checkins: Mapped[list[Checkin]] = relationship(back_populates="area")


class TaskTemplate(TimestampMixin, Base):
    __tablename__ = "task_templates"
    __table_args__ = (UniqueConstraint("user_id", "reset_day", name="uq_task_templates_user_reset_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    area_id: Mapped[int] = mapped_column(ForeignKey("areas.id", ondelete="CASCADE"), nullable=False)
    reset_day: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)

    area: Mapped[Area] = relationship(back_populates="task_templates")


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    area_id: Mapped[int] = mapped_column(ForeignKey("areas.id", ondelete="SET NULL"), nullable=True)
    template_id: Mapped[int | None] = mapped_column(ForeignKey("task_templates.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="todo", nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    area: Mapped[Area | None] = relationship(back_populates="tasks")


class HabitDefinition(TimestampMixin, Base):
    __tablename__ = "habit_definitions"
    __table_args__ = (UniqueConstraint("user_id", "slug", name="uq_habit_definitions_user_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    area_id: Mapped[int | None] = mapped_column(ForeignKey("areas.id", ondelete="SET NULL"))
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    target_value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(40))
    frequency: Mapped[str] = mapped_column(String(40), default="daily", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    area: Mapped[Area | None] = relationship(back_populates="habit_definitions")
    logs: Mapped[list[HabitLog]] = relationship(back_populates="habit")


class HabitLog(TimestampMixin, Base):
    __tablename__ = "habit_logs"
    __table_args__ = (UniqueConstraint("habit_id", "log_date", name="uq_habit_logs_habit_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    habit_id: Mapped[int] = mapped_column(ForeignKey("habit_definitions.id", ondelete="CASCADE"), nullable=False)
    log_date: Mapped[date] = mapped_column(Date, nullable=False)
    value: Mapped[float] = mapped_column(Float, default=1, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    habit: Mapped[HabitDefinition] = relationship(back_populates="logs")


class Checkin(TimestampMixin, Base):
    __tablename__ = "checkins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    area_id: Mapped[int | None] = mapped_column(ForeignKey("areas.id", ondelete="SET NULL"))
    mood: Mapped[int | None] = mapped_column(Integer)
    energy: Mapped[int | None] = mapped_column(Integer)
    stress: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)

    area: Mapped[Area | None] = relationship(back_populates="checkins")


class WorkoutSession(TimestampMixin, Base):
    __tablename__ = "workout_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    workout_type: Mapped[str] = mapped_column(String(80), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    intensity: Mapped[str] = mapped_column(String(40), default="moderate", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    exercises: Mapped[list[WorkoutExercise]] = relationship(back_populates="session", cascade="all, delete-orphan")


class WorkoutExercise(TimestampMixin, Base):
    __tablename__ = "workout_exercises"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("workout_sessions.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    sets: Mapped[int | None] = mapped_column(Integer)
    reps: Mapped[int | None] = mapped_column(Integer)
    weight: Mapped[float | None] = mapped_column(Float)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)

    session: Mapped[WorkoutSession] = relationship(back_populates="exercises")


class PlannedWorkout(TimestampMixin, Base):
    __tablename__ = "planned_workouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    plan_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="proposed", nullable=False)
    location_context: Mapped[str] = mapped_column(String(80), default="grandparents_home", nullable=False)
    goal: Mapped[str] = mapped_column(String(80), default="fat_loss", nullable=False)
    intensity: Mapped[str] = mapped_column(String(40), default="easy", nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    equipment: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    exercises: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    telegram_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    completed_workout_id: Mapped[int | None] = mapped_column(ForeignKey("workout_sessions.id", ondelete="SET NULL"))


class HealthDailySummary(TimestampMixin, Base):
    __tablename__ = "health_daily_summaries"
    __table_args__ = (UniqueConstraint("user_id", "summary_date", "source", name="uq_health_daily_summaries_user_date_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    summary_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    sleep_duration_minutes: Mapped[int | None] = mapped_column(Integer)
    sleep_quality: Mapped[int | None] = mapped_column(Integer)
    weight_kg: Mapped[float | None] = mapped_column(Float)
    body_fat_percent: Mapped[float | None] = mapped_column(Float)
    bmi: Mapped[float | None] = mapped_column(Float)
    steps: Mapped[int | None] = mapped_column(Integer)
    active_energy_kcal: Mapped[int | None] = mapped_column(Integer)
    workouts_count: Mapped[int | None] = mapped_column(Integer)
    resting_heart_rate: Mapped[int | None] = mapped_column(Integer)
    average_heart_rate: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)


class FinanceAccount(TimestampMixin, Base):
    __tablename__ = "finance_accounts"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_finance_accounts_user_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    account_type: Mapped[str] = mapped_column(String(60), default="checking", nullable=False)
    balance: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)

    transactions: Mapped[list[FinanceTransaction]] = relationship(back_populates="account")


class FinanceCategory(TimestampMixin, Base):
    __tablename__ = "finance_categories"
    __table_args__ = (UniqueConstraint("user_id", "slug", name="uq_finance_categories_user_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), default="expense", nullable=False)

    transactions: Mapped[list[FinanceTransaction]] = relationship(back_populates="category")


class FinanceImport(TimestampMixin, Base):
    __tablename__ = "finance_imports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source: Mapped[str] = mapped_column(String(120), nullable=False)
    import_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="review_pending", nullable=False)
    imported_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    raw_rows: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    review_items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)

    transactions: Mapped[list[FinanceTransaction]] = relationship(back_populates="import_record")


class FinanceTransaction(TimestampMixin, Base):
    __tablename__ = "finance_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("finance_accounts.id", ondelete="CASCADE"), nullable=False)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("finance_categories.id", ondelete="SET NULL"))
    import_id: Mapped[int | None] = mapped_column(ForeignKey("finance_imports.id", ondelete="SET NULL"))
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    external_id: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)

    account: Mapped[FinanceAccount] = relationship(back_populates="transactions")
    category: Mapped[FinanceCategory | None] = relationship(back_populates="transactions")
    import_record: Mapped[FinanceImport | None] = relationship(back_populates="transactions")


class FinanceBudget(TimestampMixin, Base):
    __tablename__ = "finance_budgets"
    __table_args__ = (UniqueConstraint("user_id", "category_id", "month", name="uq_finance_budgets_user_category_month"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("finance_categories.id", ondelete="CASCADE"), nullable=False)
    month: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)


class FinanceGoal(TimestampMixin, Base):
    __tablename__ = "finance_goals"
    __table_args__ = (UniqueConstraint("user_id", "slug", name="uq_finance_goals_user_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    target_amount: Mapped[float] = mapped_column(Float, nullable=False)
    current_amount: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    target_date: Mapped[date | None] = mapped_column(Date)


class UploadedFile(TimestampMixin, Base):
    __tablename__ = "uploaded_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(120))
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    storage_path: Mapped[str | None] = mapped_column(String(500))


class DailyPlan(TimestampMixin, Base):
    __tablename__ = "daily_plans"
    __table_args__ = (UniqueConstraint("user_id", "plan_date", name="uq_daily_plans_user_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    plan_date: Mapped[date] = mapped_column(Date, nullable=False)
    focus_area_id: Mapped[int | None] = mapped_column(ForeignKey("areas.id", ondelete="SET NULL"))
    capacity_minutes: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    tasks: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    habits: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    recommendations: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)


class DailyReview(TimestampMixin, Base):
    __tablename__ = "daily_reviews"
    __table_args__ = (UniqueConstraint("user_id", "review_date", name="uq_daily_reviews_user_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    review_date: Mapped[date] = mapped_column(Date, nullable=False)
    wins: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    blockers: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    mood: Mapped[int | None] = mapped_column(Integer)
    energy: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)


class WeeklyReview(TimestampMixin, Base):
    __tablename__ = "weekly_reviews"
    __table_args__ = (UniqueConstraint("user_id", "week_start", name="uq_weekly_reviews_user_week"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    wins: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    lessons: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    next_focus: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    score: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)


class AdviceLog(TimestampMixin, Base):
    __tablename__ = "advice_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    advice_type: Mapped[str] = mapped_column(String(80), nullable=False)
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    output_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
