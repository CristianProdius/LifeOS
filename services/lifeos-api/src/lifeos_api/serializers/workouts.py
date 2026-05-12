from __future__ import annotations

from typing import Any

from lifeos_api.models import WorkoutSession


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
