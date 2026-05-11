from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskCreate(StrictModel):
    title: str = Field(min_length=1, max_length=255)
    area: str = Field(min_length=1, max_length=80)
    priority: int = Field(default=3, ge=1, le=5)
    due_date: date | None = None
    notes: str | None = None


class TaskUpdate(StrictModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    area: str | None = Field(default=None, min_length=1, max_length=80)
    status: str | None = Field(default=None, min_length=1, max_length=40)
    priority: int | None = Field(default=None, ge=1, le=5)
    due_date: date | None = None
    notes: str | None = None


class CheckinCreate(StrictModel):
    area: str = Field(min_length=1, max_length=80)
    mood: int | None = Field(default=None, ge=1, le=10)
    energy: int | None = Field(default=None, ge=1, le=10)
    stress: int | None = Field(default=None, ge=1, le=10)
    notes: str | None = None


class HabitLogCreate(StrictModel):
    habit: str = Field(min_length=1, max_length=80)
    log_date: date
    value: float = Field(default=1, ge=0)
    notes: str | None = None


class LifeProfileUpdate(StrictModel):
    timezone: str | None = Field(default=None, min_length=1, max_length=80)
    default_context: str | None = Field(default=None, min_length=1, max_length=80)
    training_level: str | None = Field(default=None, min_length=1, max_length=80)
    goals: list[str] | None = Field(default=None, max_length=20)
    equipment: dict[str, str] | None = None


class ProfileSettingsPatch(StrictModel):
    settings: dict[str, Any]


class WorkoutRecommendationRequest(StrictModel):
    goal: str = Field(default="general", min_length=1, max_length=80)
    available_minutes: int = Field(default=30, ge=10, le=180)
    equipment: list[str] = Field(default_factory=list)
    intensity: str = Field(default="moderate", max_length=40)


class WorkoutExercisePayload(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    sets: int | None = Field(default=None, ge=1)
    reps: int | None = Field(default=None, ge=1)
    weight: float | None = Field(default=None, ge=0)
    duration_seconds: int | None = Field(default=None, ge=1)
    notes: str | None = None


class WorkoutLogCreate(StrictModel):
    session_date: date
    workout_type: str = Field(min_length=1, max_length=80)
    duration_minutes: int = Field(ge=1, le=360)
    intensity: str = Field(default="moderate", max_length=40)
    notes: str | None = None
    exercises: list[WorkoutExercisePayload] = Field(default_factory=list)


class WorkoutPlanCreate(StrictModel):
    plan_date: date
    goal: str = Field(default="fat_loss", min_length=1, max_length=80)
    available_minutes: int = Field(default=30, ge=10, le=180)
    location_context: str | None = Field(default=None, min_length=1, max_length=80)
    equipment: list[str] = Field(default_factory=list, max_length=20)
    intensity: str = Field(default="easy", min_length=1, max_length=40)
    telegram_metadata: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None


class WorkoutPlanUpdate(StrictModel):
    status: str | None = Field(default=None, min_length=1, max_length=40)
    notes: str | None = None


class WorkoutPlanComplete(StrictModel):
    notes: str | None = None


class SportTodayRequest(StrictModel):
    request_date: date | None = None
    location_context: str | None = Field(default=None, min_length=1, max_length=80)
    available_minutes: int | None = Field(default=None, ge=10, le=180)
    equipment: list[str] = Field(default_factory=list, max_length=20)
    notes: str | None = None


class SportMissedDayRequest(StrictModel):
    missed_date: date
    reason: str | None = Field(default=None, max_length=120)
    notes: str | None = None


class HealthDailySummaryUpsert(StrictModel):
    summary_date: date
    source: str = Field(min_length=1, max_length=80)
    sleep_duration_minutes: int | None = Field(default=None, ge=0, le=1440)
    sleep_quality: int | None = Field(default=None, ge=0, le=100)
    weight_kg: float | None = Field(default=None, ge=0)
    body_fat_percent: float | None = Field(default=None, ge=0, le=100)
    bmi: float | None = Field(default=None, ge=0)
    steps: int | None = Field(default=None, ge=0)
    active_energy_kcal: int | None = Field(default=None, ge=0)
    workouts_count: int | None = Field(default=None, ge=0)
    resting_heart_rate: int | None = Field(default=None, ge=0)
    average_heart_rate: int | None = Field(default=None, ge=0)
    notes: str | None = None


class FinanceImportRequest(StrictModel):
    source: str = Field(default="manual", min_length=1, max_length=120)
    rows: list[dict[str, Any]] | None = Field(default=None, max_length=1000)
    file_name: str | None = Field(default=None, max_length=255)
    content_base64: str | None = Field(default=None, max_length=8_000_000)
    content_type: str | None = Field(default=None, max_length=120)


class FinanceImportDecisionRequest(StrictModel):
    row_indexes: list[int] | None = None
    notes: str | None = None


class FinanceAffordabilityRequest(StrictModel):
    purchase_amount: float = Field(gt=0)
    monthly_income: float = Field(ge=0)
    monthly_expenses: float = Field(ge=0)
    current_savings: float = Field(default=0, ge=0)
    months: int = Field(default=1, ge=1, le=120)


class DailyPlanRequest(StrictModel):
    plan_date: date
    focus_area: str | None = Field(default=None, max_length=80)
    capacity_minutes: int = Field(default=120, ge=15, le=720)


class DailyReviewCreate(StrictModel):
    review_date: date
    wins: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    mood: int | None = Field(default=None, ge=1, le=10)
    energy: int | None = Field(default=None, ge=1, le=10)
    notes: str | None = None


class WeeklyReviewCreate(StrictModel):
    week_start: date
    wins: list[str] = Field(default_factory=list)
    lessons: list[str] = Field(default_factory=list)
    next_focus: list[str] = Field(default_factory=list)
    score: int | None = Field(default=None, ge=1, le=10)
    notes: str | None = None


class HealthResponse(BaseModel):
    status: str
    database: str
    seeded: bool


class TaskResponse(BaseModel):
    id: int
    title: str
    area: str | None
    status: str
    priority: int
    due_date: date | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
