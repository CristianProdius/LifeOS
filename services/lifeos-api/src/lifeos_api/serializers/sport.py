from __future__ import annotations

from typing import Any

from lifeos_api.models import PlannedWorkout, ProgramAdjustment, SportGoal, TrainingProgram, TrainingProgramWeek


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
        "program_id": plan.program_id,
        "program_week_id": plan.program_week_id,
        "program_day": plan.program_day,
        "source": plan.source,
        "adaptation_reason": plan.adaptation_reason,
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
    }


def sport_goal_to_dict(goal: SportGoal) -> dict[str, Any]:
    return {
        "id": goal.id,
        "name": goal.name,
        "status": goal.status,
        "start_date": goal.start_date,
        "start_weight_kg": goal.start_weight_kg,
        "target_weight_kg": goal.target_weight_kg,
        "target_date": goal.target_date,
        "stretch_weight_kg": goal.stretch_weight_kg,
        "stretch_date": goal.stretch_date,
        "healthy_weekly_loss_min_kg": goal.healthy_weekly_loss_min_kg,
        "healthy_weekly_loss_max_kg": goal.healthy_weekly_loss_max_kg,
        "notes": goal.notes,
    }


def training_program_to_dict(program: TrainingProgram) -> dict[str, Any]:
    return {
        "id": program.id,
        "sport_goal_id": program.sport_goal_id,
        "name": program.name,
        "status": program.status,
        "start_date": program.start_date,
        "duration_weeks": program.duration_weeks,
        "current_week_number": program.current_week_number,
        "default_location_context": program.default_location_context,
        "notes": program.notes,
    }


def training_program_week_to_dict(week: TrainingProgramWeek) -> dict[str, Any]:
    return {
        "id": week.id,
        "program_id": week.program_id,
        "week_number": week.week_number,
        "phase": week.phase,
        "week_start": week.week_start,
        "week_end": week.week_end,
        "target_weight_kg": week.target_weight_kg,
        "target_steps_avg": week.target_steps_avg,
        "target_active_minutes": week.target_active_minutes,
        "target_strength_sessions": week.target_strength_sessions,
        "target_cardio_sessions": week.target_cardio_sessions,
        "target_recovery_sessions": week.target_recovery_sessions,
        "plan_json": week.plan_json,
    }


def program_adjustment_to_dict(adjustment: ProgramAdjustment) -> dict[str, Any]:
    return {
        "id": adjustment.id,
        "program_id": adjustment.program_id,
        "adjustment_date": adjustment.adjustment_date,
        "reason": adjustment.reason,
        "input_payload": adjustment.input_payload,
        "output_payload": adjustment.output_payload,
        "notes": adjustment.notes,
        "created_at": adjustment.created_at,
    }
