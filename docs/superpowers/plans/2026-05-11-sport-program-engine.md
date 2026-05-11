# Sport Program Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a stored, adaptive Sport Program Engine so OpenClue generates today's workout from Cristian's 117 kg to 90 kg program instead of standalone workout suggestions.

**Architecture:** LifeOS owns goal/program state, progress scoring, workout generation, and durable planned workout links. OpenClue only calls LifeOS endpoints, renders Telegram buttons, and updates LifeOS after button actions. Existing planned workout completion stays intact; `/workouts/recommend` becomes legacy.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, Pydantic v2, Postgres 16, pytest, OpenClaw config/skills.

---

## File Structure

- Modify `services/lifeos-api/src/lifeos_api/models.py`: add sport goal/program/adjustment models and planned workout program-link columns.
- Modify `services/lifeos-api/src/lifeos_api/schemas.py`: add request schemas for `/sport/today` and `/sport/missed-day`.
- Modify `services/lifeos-api/src/lifeos_api/seed.py`: seed default sport goal and 39-week program idempotently.
- Modify `services/lifeos-api/src/lifeos_api/main.py`: add sport endpoints and helper functions.
- Create `services/lifeos-api/alembic/versions/0003_sport_program_engine.py`: create new tables and add planned workout link columns.
- Modify `services/lifeos-api/tests/test_api.py`: add API and prompt/config coverage.
- Modify `openclaw/config/openclaw.template.json`: route Sport workout/progress/missed-day behavior through new sport endpoints.
- Modify `openclaw/workspace/AGENTS.md`: document new Sport Program Engine contract.
- Modify `openclaw/workspace/skills/lifeos/SKILL.md`: document new Sport API flow and legacy cleanup.
- Modify `docs/openclaw-openclue-setup.md` if it still instructs workout generation through legacy endpoints.

## Task 1: Database Models And Migration

**Files:**
- Modify: `services/lifeos-api/src/lifeos_api/models.py`
- Create: `services/lifeos-api/alembic/versions/0003_sport_program_engine.py`
- Test: `services/lifeos-api/tests/test_api.py`

- [ ] **Step 1: Write failing seed/model visibility test**

Add to `services/lifeos-api/tests/test_api.py`:

```python
def test_sport_program_seed_is_idempotent_and_visible(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        first = client.post("/sport/program/seed")
        second = client.post("/sport/program/seed")
        active = client.get("/sport/program/active")

    assert first.status_code in {200, 201}
    assert second.status_code == 200
    assert active.status_code == 200
    payload = active.json()
    assert payload["goal"]["name"] == "Cut to 90 kg"
    assert payload["goal"]["target_weight_kg"] == 90
    assert payload["goal"]["stretch_weight_kg"] == 95
    assert payload["goal"]["stretch_date"] == "2026-08-31"
    assert payload["program"]["duration_weeks"] == 39
    assert payload["current_week"]["week_number"] == 1
```

- [ ] **Step 2: Verify test fails**

Run:

```bash
cd services/lifeos-api
uv run pytest tests/test_api.py::test_sport_program_seed_is_idempotent_and_visible -q
```

Expected: `404 Not Found` for `/sport/program/seed` or `/sport/program/active`.

- [ ] **Step 3: Add models**

In `models.py`, add classes:

```python
class SportGoal(TimestampMixin, Base):
    __tablename__ = "sport_goals"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_sport_goals_user_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="active", nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    target_weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    stretch_weight_kg: Mapped[float | None] = mapped_column(Float)
    stretch_date: Mapped[date | None] = mapped_column(Date)
    healthy_weekly_loss_min_kg: Mapped[float] = mapped_column(Float, default=0.45, nullable=False)
    healthy_weekly_loss_max_kg: Mapped[float] = mapped_column(Float, default=0.9, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
```

Also add `TrainingProgram`, `TrainingProgramWeek`, and `ProgramAdjustment` with the fields from the spec, and extend `PlannedWorkout` with `program_id`, `program_week_id`, `program_day`, `source`, and `adaptation_reason`.

- [ ] **Step 4: Add Alembic migration**

Create `0003_sport_program_engine.py` with:

```python
revision = "0003_sport_program_engine"
down_revision = "0002_lifeos_v11_core"
```

The migration creates `sport_goals`, `training_programs`, `training_program_weeks`, `program_adjustments`, and adds nullable/defaulted program columns to `planned_workouts`.

- [ ] **Step 5: Run model import and test again**

Run:

```bash
cd services/lifeos-api
uv run pytest tests/test_api.py::test_sport_program_seed_is_idempotent_and_visible -q
```

Expected: still fails because endpoints/seed functions are not implemented yet.

## Task 2: Seed Default Goal And Program

**Files:**
- Modify: `services/lifeos-api/src/lifeos_api/seed.py`
- Modify: `services/lifeos-api/src/lifeos_api/main.py`
- Test: `services/lifeos-api/tests/test_api.py`

- [ ] **Step 1: Add sport seed helpers**

In `seed.py`, add:

```python
SPORT_PROGRAM_START = date(2026, 5, 11)
SPORT_PROGRAM_END = date(2027, 2, 8)
SPORT_STRETCH_DATE = date(2026, 8, 31)
```

Add `seed_sport_program(session, user_id)` that:

- Reads latest `HealthDailySummary.weight_kg`.
- Falls back to `117`.
- Creates active `SportGoal(name="Cut to 90 kg")`.
- Creates active 39-week `TrainingProgram`.
- Creates 39 `TrainingProgramWeek` rows with deterministic weekly targets.
- Does not duplicate rows when run twice.

- [ ] **Step 2: Call seed from `seed_reset_plan`**

After profile/finance seeds, call:

```python
created += seed_sport_program(session, user.id)["created"]
```

- [ ] **Step 3: Add minimal `/sport/program/seed` and `/sport/program/active` endpoints**

In `main.py`, add routes that call seed and return active goal/program/current week.

- [ ] **Step 4: Verify test passes**

Run:

```bash
cd services/lifeos-api
uv run pytest tests/test_api.py::test_sport_program_seed_is_idempotent_and_visible -q
```

Expected: `1 passed`.

## Task 3: Program Progress Endpoint

**Files:**
- Modify: `services/lifeos-api/src/lifeos_api/main.py`
- Test: `services/lifeos-api/tests/test_api.py`

- [ ] **Step 1: Write failing low-confidence progress test**

Add:

```python
def test_sport_progress_reports_low_confidence_with_sparse_data(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        response = client.get("/sport/progress")

    assert response.status_code == 200
    payload = response.json()
    assert payload["goal"]["target_weight_kg"] == 90
    assert payload["stretch"]["weight_kg"] == 95
    assert payload["confidence"] == "low"
    assert payload["on_track_score"] >= 0
    assert payload["on_track_score"] <= 100
    assert any("weight trend" in reason.lower() for reason in payload["reasons"])
```

- [ ] **Step 2: Verify test fails**

Run:

```bash
cd services/lifeos-api
uv run pytest tests/test_api.py::test_sport_progress_reports_low_confidence_with_sparse_data -q
```

Expected: `404 Not Found`.

- [ ] **Step 3: Implement `/sport/progress`**

Compute:

- Latest weight from health summaries.
- Current week target weight.
- Stretch required pace.
- Workout adherence from current week completed program workouts.
- Movement adherence from recent steps/active energy.
- `on_track_score` using 40/30/20/10 weighting.
- `confidence` based on health summary count, completed workouts, and sync recency.

- [ ] **Step 4: Verify test passes**

Run the same test. Expected: `1 passed`.

## Task 4: Today Workout Generation

**Files:**
- Modify: `services/lifeos-api/src/lifeos_api/schemas.py`
- Modify: `services/lifeos-api/src/lifeos_api/main.py`
- Test: `services/lifeos-api/tests/test_api.py`

- [ ] **Step 1: Write failing `/sport/today` idempotency test**

Add:

```python
def test_sport_today_creates_program_linked_home_workout_idempotently(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        first = client.post("/sport/today", json={"request_date": "2026-05-11", "location_context": "grandparents_home"})
        second = client.post("/sport/today", json={"request_date": "2026-05-11", "location_context": "grandparents_home"})

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["planned_workout"]["id"] == second.json()["planned_workout"]["id"]
    planned = first.json()["planned_workout"]
    assert planned["source"] == "program"
    assert planned["program_id"] is not None
    assert planned["program_week_id"] is not None
    names = {exercise["name"].lower() for exercise in planned["exercises"]}
    assert any("walk" in name for name in names)
    assert "romanian deadlift" not in names
```

- [ ] **Step 2: Verify test fails**

Run:

```bash
cd services/lifeos-api
uv run pytest tests/test_api.py::test_sport_today_creates_program_linked_home_workout_idempotently -q
```

Expected: `404 Not Found`.

- [ ] **Step 3: Add schema and endpoint**

Add `SportTodayRequest` with optional `request_date`, `location_context`, `available_minutes`, `equipment`, and `notes`.

Implement `POST /sport/today`:

- Finds active program/current week.
- Reuses an existing proposed/accepted/started program planned workout for date.
- Creates a new `PlannedWorkout` using program-aware exercises if none exists.
- Returns `201` for created and `200` for reused.
- Logs `AdviceLog(advice_type="sport_today")`.

- [ ] **Step 4: Verify test passes**

Run same test. Expected: `1 passed`.

- [ ] **Step 5: Add gym-context test**

Add:

```python
def test_sport_today_gym_context_differs_from_home(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        response = client.post("/sport/today", json={"request_date": "2026-05-12", "location_context": "chisinau_gym"})

    assert response.status_code == 201
    names = {exercise["name"].lower() for exercise in response.json()["planned_workout"]["exercises"]}
    assert any("press" in name or "pulldown" in name or "bike" in name for name in names)
```

Run expected: `1 passed`.

## Task 5: Missed-Day Adjustment

**Files:**
- Modify: `services/lifeos-api/src/lifeos_api/schemas.py`
- Modify: `services/lifeos-api/src/lifeos_api/main.py`
- Test: `services/lifeos-api/tests/test_api.py`

- [ ] **Step 1: Write failing test**

Add:

```python
def test_sport_missed_day_creates_safe_adjustment(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        response = client.post("/sport/missed-day", json={"missed_date": "2026-05-11", "reason": "travel"})
        progress = client.get("/sport/progress")

    assert response.status_code == 201
    payload = response.json()
    assert payload["adjustment"]["reason"] == "missed_workout"
    assert "easy" in " ".join(payload["next_actions"]).lower()
    assert progress.status_code == 200
```

- [ ] **Step 2: Verify test fails**

Run:

```bash
cd services/lifeos-api
uv run pytest tests/test_api.py::test_sport_missed_day_creates_safe_adjustment -q
```

Expected: `404 Not Found`.

- [ ] **Step 3: Implement endpoint**

Add `SportMissedDayRequest` and `POST /sport/missed-day`. It creates a `ProgramAdjustment` with reason `missed_workout`, records payload, and returns safe next actions. It must not create a harder compensatory workout.

- [ ] **Step 4: Verify test passes**

Run same test. Expected: `1 passed`.

## Task 6: Cleanup OpenClue Routing And Legacy References

**Files:**
- Modify: `openclaw/config/openclaw.template.json`
- Modify: `openclaw/workspace/AGENTS.md`
- Modify: `openclaw/workspace/skills/lifeos/SKILL.md`
- Modify: `services/lifeos-api/tests/test_api.py`

- [ ] **Step 1: Write failing prompt/config test**

Extend `test_openclue_prompts_and_docs_reference_health_progress_contract` or add a new test:

```python
def test_openclue_uses_sport_program_engine_for_sport_workouts():
    repo_root = Path(__file__).resolve().parents[3]
    agents = (repo_root / "openclaw/workspace/AGENTS.md").read_text()
    skill = (repo_root / "openclaw/workspace/skills/lifeos/SKILL.md").read_text()
    config = (repo_root / "openclaw/config/openclaw.template.json").read_text()

    for text in [agents, skill, config]:
        assert "/sport/today" in text
        assert "/sport/progress" in text
        assert "/sport/missed-day" in text
    assert "Do not call /workouts/recommend for Telegram Sport" in skill
    assert "query /context/sport first, use health_progress plus recent workouts" not in config
```

- [ ] **Step 2: Verify test fails**

Run:

```bash
cd services/lifeos-api
uv run pytest tests/test_api.py::test_openclue_uses_sport_program_engine_for_sport_workouts -q
```

Expected: assertion failure.

- [ ] **Step 3: Update OpenClue config and docs**

Update prompts:

- "What workout today?" -> `POST /sport/today`.
- "Am I on track?" -> `GET /sport/progress`.
- Missed day -> `POST /sport/missed-day`.
- `/workouts/recommend` is legacy and not used for Telegram Sport flows.
- `/workouts/plan` remains lower-level/manual.

- [ ] **Step 4: Verify test passes**

Run same test. Expected: `1 passed`.

## Task 7: Full Verification And Deployment

**Files:**
- All touched files.

- [ ] **Step 1: Run full local tests**

Run:

```bash
cd services/lifeos-api
uv run pytest tests/test_api.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Validate OpenClaw config and Compose**

Run:

```bash
python3 -m json.tool openclaw/config/openclaw.template.json >/tmp/lifeos-openclaw-template.valid
docker compose --env-file .env.example config >/tmp/lifeos-compose-config.yml
```

Expected: both commands exit 0.

- [ ] **Step 3: Commit and push**

Run:

```bash
git add services/lifeos-api openclaw docs
git commit -m "feat: add sport program engine"
git push origin codex/sport-program-engine
git push origin HEAD:main
```

- [ ] **Step 4: Deploy to VPS**

Run:

```bash
ssh jira-microlab-automation 'cd /opt/lifeos && ./scripts/backup.sh'
rsync -avR ./services/lifeos-api ./openclaw ./docs jira-microlab-automation:/opt/lifeos/
ssh jira-microlab-automation 'cd /opt/lifeos && ./scripts/render-openclaw-config.sh && chown -R 1000:1000 openclaw/config && docker compose --env-file .env build lifeos-api lifeos-migrate && docker compose --env-file .env up -d lifeos-api && docker compose --env-file .env restart openclue-gateway'
```

- [ ] **Step 5: Verify live endpoints**

Run:

```bash
ssh jira-microlab-automation 'cd /opt/lifeos && set -a && . ./.env && set +a && curl -fsS -H "X-API-Key: $LIFEOS_API_TOKEN" http://127.0.0.1:8080/sport/program/active >/tmp/lifeos-sport-active.json && curl -fsS -H "X-API-Key: $LIFEOS_API_TOKEN" http://127.0.0.1:8080/sport/progress >/tmp/lifeos-sport-progress.json'
```

Expected: both curl commands exit 0 and gateway logs show `thinking=low, fast=on`.
