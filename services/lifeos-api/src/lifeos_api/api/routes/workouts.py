from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from lifeos_api.api.deps import get_session
from lifeos_api.domain.profile import get_or_create_life_profile
from lifeos_api.domain.workouts import (
    PLANNED_WORKOUT_STATUSES,
    PlannedWorkoutNotFoundError,
    build_planned_workout,
    build_workout_recommendation,
    complete_planned_workout,
    get_planned_workout_or_404,
)
from lifeos_api.models import AdviceLog, PlannedWorkout, WorkoutExercise, WorkoutSession
from lifeos_api.schemas import (
    WorkoutLogCreate,
    WorkoutPlanComplete,
    WorkoutPlanCreate,
    WorkoutPlanUpdate,
    WorkoutRecommendationRequest,
)
from lifeos_api.seed import get_or_create_user
from lifeos_api.serializers import planned_workout_to_dict, workout_to_dict

router = APIRouter()


@router.post("/workouts/recommend")
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


@router.post("/workouts/log", status_code=status.HTTP_201_CREATED)
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


@router.post("/workouts/plan", status_code=status.HTTP_201_CREATED)
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


@router.get("/workouts/plans/{plan_id}")
def get_workout_plan(plan_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    user, _ = get_or_create_user(session)
    try:
        plan = get_planned_workout_or_404(session, user.id, plan_id)
    except PlannedWorkoutNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="planned workout not found") from exc
    return planned_workout_to_dict(plan)


@router.patch("/workouts/plans/{plan_id}")
def update_workout_plan(
    plan_id: int,
    payload: WorkoutPlanUpdate,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    user, _ = get_or_create_user(session)
    try:
        plan = get_planned_workout_or_404(session, user.id, plan_id)
    except PlannedWorkoutNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="planned workout not found") from exc
    updates = payload.model_dump(exclude_unset=True)
    if "status" in updates and updates["status"] is not None:
        if updates["status"] not in PLANNED_WORKOUT_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="invalid planned workout status",
            )
        plan.status = updates["status"]
    if "notes" in updates:
        plan.notes = updates["notes"]
    session.commit()
    session.refresh(plan)
    return planned_workout_to_dict(plan)


@router.post("/workouts/plans/{plan_id}/complete")
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
    complete_planned_workout(session, user.id, plan, notes=payload.notes)
    session.commit()
    session.refresh(plan)
    return planned_workout_to_dict(plan)
