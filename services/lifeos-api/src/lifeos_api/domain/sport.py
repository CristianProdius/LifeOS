from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from lifeos_api.core.time import lifeos_today
from lifeos_api.domain.health import build_health_progress
from lifeos_api.domain.workouts import build_planned_workout
from lifeos_api.models import (
    AdviceLog,
    HealthDailySummary,
    PlannedWorkout,
    ProgramAdjustment,
    SportGoal,
    TrainingProgram,
    TrainingProgramWeek,
)
from lifeos_api.schemas import SportMissedDayRequest, SportTodayRequest
from lifeos_api.seed import seed_sport_program
from lifeos_api.serializers import (
    planned_workout_to_dict,
    program_adjustment_to_dict,
    sport_goal_to_dict,
    training_program_to_dict,
    training_program_week_to_dict,
)
from lifeos_api.utils import jsonable_data, rounded_metric, slugify


class SportProgramError(RuntimeError):
    """Raised when the active sport program cannot be resolved."""

    detail = "sport program error"

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.detail
        super().__init__(self.detail)


class SportProgramSeedError(SportProgramError):
    """Raised when seeding does not create an active sport goal and program."""

    detail = "sport program seed failed"


class SportProgramWeekNotFoundError(SportProgramError):
    """Raised when the current training program week is missing."""

    detail = "current sport program week missing"


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
    sport_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request_date = payload.request_date or lifeos_today()
    goal, program = get_active_sport_goal_and_program(session, user_id)
    current_week = get_current_program_week(session, program, request_date)
    sport_settings = sport_settings or {}
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
        exercises=jsonable_data(exercises),
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
            output_payload=jsonable_data(output),
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
        if goal is None:
            raise SportProgramSeedError()
        program = session.scalar(
            select(TrainingProgram).where(
                TrainingProgram.user_id == user_id,
                TrainingProgram.sport_goal_id == goal.id,
                TrainingProgram.status == "active",
            )
        )
    if goal is None or program is None:
        raise SportProgramSeedError()
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
        raise SportProgramWeekNotFoundError()
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
