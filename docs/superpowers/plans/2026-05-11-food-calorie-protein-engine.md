# Food Calorie Protein Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a LifeOS Food Engine that stores meals, calculates calorie/protein targets, summarizes daily adherence, and gives OpenClue reliable nutrition context.

**Architecture:** Add focused SQLAlchemy models and Alembic migration for food targets/logs/reviews. Keep endpoint implementation in the existing FastAPI app for consistency with current LifeOS patterns. Compute daily summaries and progress from source rows so OpenClue sees current data without duplicated summary state.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, Pydantic v2, pytest, Postgres/SQLite.

---

### Task 1: Food API Tests

**Files:**
- Modify: `services/lifeos-api/tests/test_api.py`

- [ ] Add failing tests for `GET /food/target`, `POST /food/logs`, `PATCH /food/logs/{id}`, `GET /food/daily-summary`, `GET /food/progress`, and `GET /context/food`.
- [ ] Run `uv run pytest tests/test_api.py -q` from `services/lifeos-api` and confirm the new tests fail because the endpoints and schema do not exist.

### Task 2: Database And Schemas

**Files:**
- Modify: `services/lifeos-api/src/lifeos_api/models.py`
- Modify: `services/lifeos-api/src/lifeos_api/schemas.py`
- Create: `services/lifeos-api/alembic/versions/0005_food_calorie_protein_engine.py`

- [ ] Add `FoodTarget`, `FoodLog`, `FoodLogItem`, and `FoodDailyReview`.
- [ ] Add Pydantic payload classes for target recalculation, food log create/update, food item payload, and food review create.
- [ ] Add Alembic migration with idempotent table creation checks.

### Task 3: Target And Summary Engine

**Files:**
- Modify: `services/lifeos-api/src/lifeos_api/main.py`

- [ ] Add food constants for age, height, activity factor, starting calories, protein, and calorie floor.
- [ ] Add helpers for active target creation, Mifflin-St Jeor calculation, latest weight lookup, daily summary aggregation, progress aggregation, and adjustment recommendation.
- [ ] Ensure missing food logs produce `data_quality` warnings rather than false adherence.

### Task 4: FastAPI Endpoints

**Files:**
- Modify: `services/lifeos-api/src/lifeos_api/main.py`

- [ ] Implement `GET /food/target`.
- [ ] Implement `POST /food/target/recalculate`.
- [ ] Implement `POST /food/logs`.
- [ ] Implement `PATCH /food/logs/{id}`.
- [ ] Implement `GET /food/daily-summary`.
- [ ] Implement `GET /food/progress`.
- [ ] Implement `POST /food/reviews/daily`.
- [ ] Extend `/context/food` with target, today summary, and progress.

### Task 5: OpenClue Food Contract

**Files:**
- Modify: `openclaw/workspace/AGENTS.md`
- Modify: `openclaw/workspace/skills/lifeos/SKILL.md`
- Modify: `openclaw/config/openclaw.template.json`
- Modify: `docs/openclaw-openclue-setup.md`

- [ ] Require Food topic to query food endpoints before advice.
- [ ] Require OpenClue to log food before claiming it is tracked.
- [ ] Document estimate confidence and missing-log behavior.
- [ ] Mention Telegram buttons for food confirmation/edit/delete as the expected presentation.

### Task 6: Verification, Commit, Push, Deploy

**Files:**
- All changed files.

- [ ] Run `uv run pytest tests/test_api.py -q`.
- [ ] Run `python3 -m json.tool openclaw/config/openclaw.template.json`.
- [ ] Run `docker compose --env-file .env.example config`.
- [ ] Commit with `feat: add food calorie protein engine`.
- [ ] Push `codex/food-calorie-protein-engine` and update `main` if verification passes.
- [ ] Back up VPS Postgres, deploy to `/opt/lifeos`, run migrations, restart `lifeos-api` and `openclue-gateway`, and verify `/context/food`.
