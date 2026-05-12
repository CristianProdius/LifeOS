from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from lifeos_api.api.deps import get_session
from lifeos_api.models import DailyReview, WeeklyReview
from lifeos_api.schemas import DailyReviewCreate, WeeklyReviewCreate
from lifeos_api.seed import get_or_create_user
from lifeos_api.serializers import daily_review_to_dict, weekly_review_to_dict

router = APIRouter()


@router.post("/reviews/daily", status_code=status.HTTP_201_CREATED)
def create_daily_review(payload: DailyReviewCreate, session: Session = Depends(get_session)) -> dict[str, Any]:
    user, _ = get_or_create_user(session)
    review = session.scalar(
        select(DailyReview).where(DailyReview.user_id == user.id, DailyReview.review_date == payload.review_date)
    )
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


@router.post("/reviews/weekly", status_code=status.HTTP_201_CREATED)
def create_weekly_review(payload: WeeklyReviewCreate, session: Session = Depends(get_session)) -> dict[str, Any]:
    user, _ = get_or_create_user(session)
    review = session.scalar(
        select(WeeklyReview).where(WeeklyReview.user_id == user.id, WeeklyReview.week_start == payload.week_start)
    )
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
