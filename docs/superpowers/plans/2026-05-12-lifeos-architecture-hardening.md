# LifeOS Architecture Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor LifeOS from a working V1 monolith into a maintainable product architecture that can absorb Sport, Food, Finance, Health, Daily, Telegram, and future integrations without becoming prompt/code sprawl.

**Architecture:** Keep FastAPI, SQLAlchemy, Alembic, and OpenClaw, but split responsibilities by domain. The API should have thin route modules, domain service modules, serializer modules, shared core utilities, and one source of truth for the OpenClue behavior contract that renders into OpenClaw config/docs.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2, pytest, Docker Compose, OpenClaw.

---

## Current Audit

The current LifeOS project is functional and tested, but it is not yet a professional long-term architecture.

Strengths:

- Docker Compose separation is good: gateway, API, DB, migrations, backup.
- Alembic migrations exist and are ordered.
- Seed data is idempotent.
- API tests pass and cover real user flows.
- OpenClue is instructed to read/write LifeOS before claiming state.
- Deployment now has a safe VPS deploy script and runtime-state protections.

Main risks:

- `services/lifeos-api/src/lifeos_api/main.py` is about 2,500 lines and contains routes, auth, domain logic, serializers, finance import parsing, food calculations, sport planning, and workout generation.
- `services/lifeos-api/tests/test_api.py` is about 1,100 lines and mixes all domains.
- OpenClue behavior is duplicated across `openclaw/workspace/AGENTS.md`, `openclaw/workspace/skills/lifeos/SKILL.md`, `openclaw/config/openclaw.template.json`, setup docs, and prompt tests.
- Personalization and program defaults live as Python constants in `seed.py`; they are usable but not a clean contract for future editing.
- New features can currently be added by appending code to `main.py`, which is exactly how the project becomes a vibe-coded mess.

## Target Structure

Create this structure:

```text
services/lifeos-api/src/lifeos_api/
  app.py
  main.py
  api/
    __init__.py
    deps.py
    routes/
      __init__.py
      checkins.py
      context.py
      daily.py
      finance.py
      food.py
      habits.py
      health.py
      profile.py
      reviews.py
      sport.py
      tasks.py
      workouts.py
  core/
    __init__.py
    config.py
    security.py
    time.py
  domain/
    __init__.py
    context.py
    daily.py
    finance.py
    food.py
    health.py
    profile.py
    sport.py
    tasks.py
    workouts.py
  serializers/
    __init__.py
    finance.py
    food.py
    health.py
    profile.py
    sport.py
    tasks.py
    workouts.py
```

OpenClue contract target:

```text
openclaw/contracts/
  lifeos_contract.json
scripts/
  render-openclue-contract.py
```

Test target:

```text
services/lifeos-api/tests/
  conftest.py
  test_auth_health.py
  test_context_profile.py
  test_food.py
  test_health.py
  test_sport.py
  test_finance.py
  test_daily_reviews.py
  test_openclue_contract.py
```

## Architecture Rules

- `main.py` may only expose the ASGI factory/import path after refactor.
- `app.py` creates the FastAPI app and includes routers.
- Route modules validate HTTP payloads and call domain services. They should not contain business calculations.
- Domain modules own business decisions and database writes.
- Serializer modules convert ORM objects to API dictionaries.
- OpenClue behavior rules must be edited in one contract source and rendered into config/docs.
- Prompt/config tests should compare generated output or contract references, not rely on copied text scattered everywhere.
- No new large feature should add more domain logic to the current `main.py`.

## Task 1: Add Architecture Guard Tests

**Files:**

- Create: `services/lifeos-api/tests/test_architecture.py`
- Modify: `scripts/verify.sh`

- [ ] **Step 1: Write architecture guard tests**

Create `services/lifeos-api/tests/test_architecture.py`:

```python
from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
API_ROOT = REPO_ROOT / "services/lifeos-api/src/lifeos_api"


def test_main_py_does_not_grow_past_current_monolith_limit():
    main_py = API_ROOT / "main.py"
    line_count = len(main_py.read_text(encoding="utf-8").splitlines())
    assert line_count <= 2600


def test_no_runtime_artifacts_are_tracked():
    tracked = (REPO_ROOT / ".git").exists()
    assert tracked is True
    forbidden = [
        "services/lifeos-api/.venv",
        "services/lifeos-api/.pytest_cache",
        "openclaw/config/openclaw.json",
        "__pycache__",
    ]
    git_files = set()
    import subprocess

    output = subprocess.check_output(["git", "ls-files"], cwd=REPO_ROOT, text=True)
    git_files.update(output.splitlines())
    for path in git_files:
        assert not any(item in path for item in forbidden)


def test_create_app_remains_available_during_refactor():
    main_py = API_ROOT / "main.py"
    module = ast.parse(main_py.read_text(encoding="utf-8"))
    names = {node.name for node in module.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "create_app" in names
```

- [ ] **Step 2: Run test to verify it passes on current code**

Run:

```bash
cd services/lifeos-api
uv run pytest tests/test_architecture.py
```

Expected: pass.

- [ ] **Step 3: Add architecture test to verification**

Modify `scripts/verify.sh` to run:

```bash
(
  cd services/lifeos-api
  uv run pytest tests/test_architecture.py
)
```

- [ ] **Step 4: Run verification**

Run:

```bash
./scripts/verify.sh
```

Expected: infrastructure verification passes and architecture tests pass.

## Task 2: Extract Core App, Dependencies, Security, And Time

**Files:**

- Create: `services/lifeos-api/src/lifeos_api/app.py`
- Create: `services/lifeos-api/src/lifeos_api/api/__init__.py`
- Create: `services/lifeos-api/src/lifeos_api/api/deps.py`
- Create: `services/lifeos-api/src/lifeos_api/core/__init__.py`
- Create: `services/lifeos-api/src/lifeos_api/core/security.py`
- Create: `services/lifeos-api/src/lifeos_api/core/time.py`
- Modify: `services/lifeos-api/src/lifeos_api/main.py`
- Test: `services/lifeos-api/tests/test_auth_health.py`

- [ ] **Step 1: Move API key functions**

Move these functions from `main.py` to `core/security.py`:

```python
require_api_key
require_shortcut_token
bearer_token
```

Keep signatures unchanged.

- [ ] **Step 2: Move Moldova time helpers**

Move these constants/functions from `main.py` to `core/time.py`:

```python
LIFEOS_DEFAULT_TIMEZONE
lifeos_today
```

- [ ] **Step 3: Move session dependency**

Move `get_session` into `api/deps.py`. It should read `request.app.state.session_factory` exactly as the current implementation does.

- [ ] **Step 4: Create app factory module**

Create `app.py` with `create_app(database_url: str | None = None, seed_database: bool = True) -> FastAPI`.

For this task, it may still register the existing routes from `main.py` through a helper until routers are extracted. The goal is to make `main.py` a compatibility import:

```python
from lifeos_api.app import create_app

__all__ = ["create_app"]
```

- [ ] **Step 5: Run full tests**

Run:

```bash
cd services/lifeos-api
uv run pytest
```

Expected: all tests pass.

## Task 3: Extract Serializers

**Files:**

- Create: `services/lifeos-api/src/lifeos_api/serializers/__init__.py`
- Create: `services/lifeos-api/src/lifeos_api/serializers/profile.py`
- Create: `services/lifeos-api/src/lifeos_api/serializers/tasks.py`
- Create: `services/lifeos-api/src/lifeos_api/serializers/workouts.py`
- Create: `services/lifeos-api/src/lifeos_api/serializers/sport.py`
- Create: `services/lifeos-api/src/lifeos_api/serializers/health.py`
- Create: `services/lifeos-api/src/lifeos_api/serializers/food.py`
- Create: `services/lifeos-api/src/lifeos_api/serializers/finance.py`
- Modify: `services/lifeos-api/src/lifeos_api/main.py`

- [ ] **Step 1: Move pure `*_to_dict` functions**

Move these functions out of `main.py` without changing output:

```text
profile_to_dict
area_to_dict
task_to_dict
habit_to_dict
habit_log_to_dict
checkin_to_dict
workout_to_dict
planned_workout_to_dict
sport_goal_to_dict
training_program_to_dict
training_program_week_to_dict
program_adjustment_to_dict
health_daily_summary_to_dict
food_target_to_dict
food_log_to_dict
food_log_item_to_dict
food_daily_review_to_dict
daily_plan_to_dict
daily_review_to_dict
weekly_review_to_dict
finance_import_to_dict
```

- [ ] **Step 2: Preserve imports through the transition**

Import moved functions in `main.py` from serializer modules.

- [ ] **Step 3: Run domain tests**

Run:

```bash
cd services/lifeos-api
uv run pytest
```

Expected: all tests pass.

## Task 4: Extract Domain Services

**Files:**

- Create: `services/lifeos-api/src/lifeos_api/domain/health.py`
- Create: `services/lifeos-api/src/lifeos_api/domain/food.py`
- Create: `services/lifeos-api/src/lifeos_api/domain/sport.py`
- Create: `services/lifeos-api/src/lifeos_api/domain/finance.py`
- Create: `services/lifeos-api/src/lifeos_api/domain/workouts.py`
- Create: `services/lifeos-api/src/lifeos_api/domain/daily.py`
- Modify: `services/lifeos-api/src/lifeos_api/main.py`

- [ ] **Step 1: Move health logic**

Move:

```text
upsert_health_summary
build_health_progress
health_progress_summary_to_dict
health_metric_values
rounded_metric
```

- [ ] **Step 2: Move food logic**

Move:

```text
get_or_create_active_food_target
create_food_target
build_food_target_calculation
latest_food_weight_kg
food_log_item_from_payload
get_food_log_or_404
build_food_daily_summary
food_totals
build_food_adherence
build_food_progress_context
food_weight_entries
build_food_weight_trend
build_food_adjustment
```

- [ ] **Step 3: Move sport logic**

Move:

```text
sport_program_context
build_sport_progress
create_or_reuse_sport_today_workout
create_missed_day_adjustment
get_active_sport_goal_and_program
get_current_program_week
recent_health_summaries
weekly_adherence
required_weekly_loss
sport_next_actions
infer_location_context
personalized_default_minutes
personalized_focus
has_poor_sleep_signal
program_focus_for_day
has_recent_missed_adjustment
append_note
default_minutes_for_week
intensity_for_week
add_program_notes_to_exercises
sport_today_response
```

- [ ] **Step 4: Move workout-generation logic**

Move:

```text
build_workout_recommendation
build_planned_workout
exercise_payload_from_plan
get_planned_workout_or_404
```

- [ ] **Step 5: Move finance import logic**

Move:

```text
rows_from_import_payload
maybe_store_upload
normalize_finance_row
coerce_date
coerce_amount
transaction_external_id
get_or_create_account
get_or_create_category
get_finance_import_or_404
finance_import_status
```

- [ ] **Step 6: Run tests after each domain move**

Run after each step:

```bash
cd services/lifeos-api
uv run pytest
```

Expected: all tests pass after every move.

## Task 5: Extract Routers

**Files:**

- Create route modules under `services/lifeos-api/src/lifeos_api/api/routes/`
- Modify: `services/lifeos-api/src/lifeos_api/app.py`
- Modify: `services/lifeos-api/src/lifeos_api/main.py`

- [ ] **Step 1: Create one router per domain**

Each route module should define:

```python
from fastapi import APIRouter

router = APIRouter()
```

Use these prefixes:

```text
profile.py    -> no prefix for /profile
context.py    -> no prefix for /context/{area}
sport.py      -> no prefix for /sport/*
workouts.py   -> no prefix for /workouts/*
health.py     -> no prefix for /health and /health/daily-summaries
food.py       -> no prefix for /food/*
finance.py    -> no prefix for /finance/*
daily.py      -> no prefix for /daily/plan
reviews.py    -> no prefix for /reviews/*
tasks.py      -> no prefix for /tasks/*
habits.py     -> no prefix for /habits/log
checkins.py   -> no prefix for /checkins
```

- [ ] **Step 2: Include routers in `app.py`**

```python
for router in [
    health.router,
    profile.router,
    context.router,
    sport.router,
    workouts.router,
    food.router,
    finance.router,
    daily.router,
    reviews.router,
    tasks.router,
    habits.router,
    checkins.router,
]:
    app.include_router(router)
```

- [ ] **Step 3: Shrink `main.py`**

After route extraction, `main.py` should only contain:

```python
from lifeos_api.app import create_app

__all__ = ["create_app"]
```

- [ ] **Step 4: Run tests**

Run:

```bash
cd services/lifeos-api
uv run pytest
```

Expected: all tests pass.

## Task 6: Split Tests By Domain

**Files:**

- Create: `services/lifeos-api/tests/conftest.py`
- Create: domain test files listed in the target structure
- Delete or shrink: `services/lifeos-api/tests/test_api.py`

- [ ] **Step 1: Move `make_client` fixture to `conftest.py`**

Use:

```python
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'lifeos-test.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("LIFEOS_API_KEY", "test-token")

    from lifeos_api.main import create_app

    app = create_app(database_url=database_url, seed_database=True)
    with TestClient(app, headers={"X-API-Key": "test-token"}) as test_client:
        yield test_client
```

- [ ] **Step 2: Move tests by endpoint domain**

Move existing tests without changing assertions.

- [ ] **Step 3: Run all tests**

Run:

```bash
cd services/lifeos-api
uv run pytest
```

Expected: all tests pass.

## Task 7: Centralize OpenClue Contract

**Files:**

- Create: `openclaw/contracts/lifeos_contract.json`
- Create: `scripts/render-openclue-contract.py`
- Modify: `openclaw/workspace/AGENTS.md`
- Modify: `openclaw/workspace/skills/lifeos/SKILL.md`
- Modify: `openclaw/config/openclaw.template.json`
- Modify: `services/lifeos-api/tests/test_openclue_contract.py`
- Modify: `scripts/verify.sh`

- [ ] **Step 1: Create contract JSON**

Define:

```json
{
  "assistant_name": "OpenClue",
  "source_of_truth": "LifeOS API",
  "forbidden_tools": ["memory_search"],
  "required_context_reads": {
    "sport": ["/context/sport", "/sport/today", "/sport/progress"],
    "food": ["/context/food", "/food/target", "/food/daily-summary", "/food/progress"],
    "finance": ["/context/finance", "/finance/summary"],
    "health": ["/context/health"],
    "daily": ["/context/daily"]
  },
  "write_before_claiming": [
    "food logs",
    "planned workouts",
    "task status",
    "habit logs",
    "finance imports"
  ],
  "button_callbacks": {
    "workout": ["start", "done", "too_hard", "change", "skip"],
    "food": ["looks_right", "edit_calories", "add_protein", "delete"]
  }
}
```

- [ ] **Step 2: Render generated sections**

`scripts/render-openclue-contract.py` should update only marked generated sections:

```text
<!-- BEGIN GENERATED LIFEOS CONTRACT -->
...
<!-- END GENERATED LIFEOS CONTRACT -->
```

- [ ] **Step 3: Add contract freshness test**

The test should run the renderer into a temp copy or compare expected generated strings and fail if config/docs drift from `lifeos_contract.json`.

- [ ] **Step 4: Add renderer check to `scripts/verify.sh`**

Verification should fail if generated contract output is stale.

## Task 8: Move Seed Defaults Into Versioned Data

**Files:**

- Create: `services/lifeos-api/src/lifeos_api/data/areas.json`
- Create: `services/lifeos-api/src/lifeos_api/data/habits.json`
- Create: `services/lifeos-api/src/lifeos_api/data/reset_plan.json`
- Create: `services/lifeos-api/src/lifeos_api/data/personalization.json`
- Create: `services/lifeos-api/src/lifeos_api/data/sport_program.json`
- Modify: `services/lifeos-api/src/lifeos_api/seed.py`
- Modify: `services/lifeos-api/pyproject.toml`

- [ ] **Step 1: Load seed data from package resources**

Use `importlib.resources.files("lifeos_api.data")`.

- [ ] **Step 2: Keep existing seed idempotency tests passing**

Run:

```bash
cd services/lifeos-api
uv run pytest tests/test_auth_health.py tests/test_context_profile.py tests/test_sport.py
```

Expected: all tests pass.

## Task 9: Final Verification

- [ ] **Step 1: Run API tests**

```bash
cd services/lifeos-api
uv run pytest
```

Expected: all tests pass.

- [ ] **Step 2: Run infrastructure verification**

```bash
./scripts/verify.sh
```

Expected: verification passes.

- [ ] **Step 3: Run Docker config check**

```bash
docker compose --env-file .env.example config --quiet
```

Expected: exit code 0.

- [ ] **Step 4: Deploy with safe deploy script**

```bash
./scripts/deploy-vps.sh
```

Expected: deploy completes and prints that OpenClaw cron has 5 jobs.

## Success Criteria

- `main.py` is a compatibility shim, not a 2,500-line domain file.
- New features have a clear destination: route, domain service, serializer, schema, migration, tests.
- OpenClue prompts come from one contract source or have generated sections checked by tests.
- Tests are split by domain and can be run independently.
- Deployment guard remains in place and verifies cron state.
- No runtime auth, cron, Telegram, OpenClaw workspace state, `.venv`, `.pytest_cache`, or `__pycache__` files are tracked.
