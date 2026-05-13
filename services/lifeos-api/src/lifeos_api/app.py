from __future__ import annotations

import os

from fastapi import Depends, FastAPI

from lifeos_api.api.routes import (
    checkins,
    context,
    daily,
    finance,
    food,
    habits,
    health,
    profile,
    reviews,
    sport,
    tasks,
    telegram_actions,
    workouts,
)
from lifeos_api.core.security import require_api_key
from lifeos_api.database import create_engine_and_session, get_database_url, init_database
from lifeos_api.seed import seed_reset_plan


def create_app(database_url: str | None = None, seed_database: bool = True) -> FastAPI:
    engine, session_factory = create_engine_and_session(database_url)
    effective_database_url = database_url or get_database_url()
    auto_create_schema = effective_database_url.startswith("sqlite") or os.getenv(
        "LIFEOS_AUTO_CREATE_SCHEMA", ""
    ).lower() in {"1", "true", "yes"}
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

    app.include_router(health.router)
    app.include_router(profile.router)
    app.include_router(context.router)
    app.include_router(sport.router)
    app.include_router(workouts.router)
    app.include_router(food.router)
    app.include_router(finance.router)
    app.include_router(daily.router)
    app.include_router(reviews.router)
    app.include_router(tasks.router)
    app.include_router(habits.router)
    app.include_router(checkins.router)
    app.include_router(telegram_actions.router)

    return app


__all__ = ["create_app"]
