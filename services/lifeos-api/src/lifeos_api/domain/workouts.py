from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from lifeos_api.models import PlannedWorkout
from lifeos_api.schemas import WorkoutRecommendationRequest
from lifeos_api.utils import slugify

PLANNED_WORKOUT_STATUSES = {"proposed", "accepted", "started", "completed", "skipped", "replaced"}


class PlannedWorkoutNotFoundError(LookupError):
    """Raised when a planned workout cannot be found for a user."""


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
    focus: str | None = None,
    sport_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_location = slugify(location_context).replace("-", "_")
    equipment_set = {slugify(item).replace("-", "_") for item in equipment}
    normalized_focus = slugify(focus or "").replace("-", "_")
    sport_settings = sport_settings or {}
    swimming_baseline = sport_settings.get("swimming_baseline", {})
    if normalized_focus == "poor_sleep_recovery":
        exercises = [
            {"name": "Easy recovery walk", "duration_seconds": min(available_minutes, 20) * 60, "notes": "Poor sleep detected; keep this easy."},
            {"name": "Mobility flow", "duration_seconds": 480, "notes": "Hips, ankles, upper back, shoulders; no lateral raises."},
            {"name": "Breathing downshift", "duration_seconds": 240},
        ]
    elif normalized_focus == "recovery":
        exercises = [
            {"name": "Easy walk", "duration_seconds": min(available_minutes, 20) * 60, "notes": "Keep this intentionally easy."},
            {"name": "Mobility flow", "duration_seconds": 420, "notes": "Hips, ankles, upper back, shoulders."},
            {"name": "Breathing downshift", "duration_seconds": 240},
        ]
    elif normalized_focus == "swim_low_impact":
        repeat_distance = int(swimming_baseline.get("repeat_distance_m", 50))
        rest_seconds = int(swimming_baseline.get("rest_seconds", 20))
        exercises = [
            {"name": "Easy swim warm-up", "duration_seconds": 600, "notes": "Relaxed pace."},
            {
                "name": "Swim repeats",
                "duration_seconds": max((available_minutes - 20) * 60, 1200),
                "notes": f"Repeat {repeat_distance} m, rest about {rest_seconds} seconds, then repeat. Stay smooth, not all-out.",
            },
            {"name": "Technique cooldown", "duration_seconds": 600, "notes": "Easy laps or backstroke; leave the pool feeling better."},
        ]
    elif normalized_focus == "gym_full_body":
        exercises = [
            {"name": "Treadmill walk", "duration_seconds": 480, "notes": "Warm up at easy pace."},
            {"name": "Goblet squat to box", "sets": 2, "reps": 10, "notes": "RPE 6-7, controlled depth."},
            {"name": "Chest press", "sets": 2, "reps": 10, "notes": "Controlled reps; no shoulder pain."},
            {"name": "Seated cable row", "sets": 2, "reps": 10, "notes": "Keep traps relaxed."},
            {"name": "Lat pulldown", "sets": 2, "reps": 10, "notes": "No neck strain."},
            {"name": "Stationary bike", "duration_seconds": max((available_minutes - 35) * 60, 600), "notes": "Zone 2 finish."},
        ]
    elif normalized_focus == "home_midday_bodyweight":
        exercises = [
            {"name": "Easy walk warm-up", "duration_seconds": 600},
            {"name": "Dead hang practice", "sets": 3, "duration_seconds": 10, "notes": "Stop before hand pain changes form."},
            {"name": "Incline push-ups", "sets": 2, "reps": 10, "notes": "Leave reps in reserve."},
            {"name": "Chair squats", "sets": 2, "reps": 12, "notes": "Smooth reps, no rushing."},
            {"name": "Mobility cooldown", "duration_seconds": 420, "notes": "Modified low-impact only; no jumping HIIT."},
        ]
    elif normalized_focus == "long_walk":
        exercises = [
            {"name": "Easy long walk", "duration_seconds": max((available_minutes - 5) * 60, 1200), "notes": "Comfortable pace, no jogging."},
            {"name": "Mobility cooldown", "duration_seconds": 300},
        ]
    elif normalized_location in {"grandparents_home", "home"} and normalized_focus == "strength_basics":
        exercises = [
            {"name": "Easy walk warm-up", "duration_seconds": 480},
            {"name": "Chair squats", "sets": 2, "reps": 8, "notes": "Stop if knees hurt."},
            {"name": "Wall push-ups", "sets": 2, "reps": 8, "notes": "Keep it easy and controlled."},
            {"name": "Dead bug", "sets": 2, "reps": 8, "notes": "Slow reps; keep lower back controlled."},
            {"name": "Mobility cooldown", "duration_seconds": 300},
        ]
    elif normalized_location in {"grandparents_home", "home"}:
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
        "focus": normalized_focus or None,
        "exercises": exercises,
    }


def exercise_payload_from_plan(exercise: dict[str, Any]) -> dict[str, Any]:
    allowed = {"name", "sets", "reps", "weight", "duration_seconds", "notes"}
    return {key: value for key, value in exercise.items() if key in allowed and value is not None}


def get_planned_workout_or_404(session: Session, user_id: int, plan_id: int) -> PlannedWorkout:
    plan = session.scalar(select(PlannedWorkout).where(PlannedWorkout.id == plan_id, PlannedWorkout.user_id == user_id))
    if plan is None:
        raise PlannedWorkoutNotFoundError(plan_id)
    return plan
