# Sport Personalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store Cristian's sport, food, sleep, productivity, and coaching personalization as LifeOS data and use it when OpenClue generates daily Sport plans.

**Architecture:** Add a small `profile_settings` table keyed by domain so personalization is structured but flexible. Seed default settings from the approved interview, expose them through `/profile` and relevant contexts, and update `/sport/today` to choose gym, swim, home, recovery, and intensity from those settings.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, Pydantic v2, Postgres 16, pytest, OpenClaw prompt/config docs.

---

## File Structure

- Modify `services/lifeos-api/src/lifeos_api/models.py`: add `ProfileSetting`.
- Create `services/lifeos-api/alembic/versions/0004_profile_settings.py`: create `profile_settings`.
- Modify `services/lifeos-api/src/lifeos_api/seed.py`: seed default personalization settings and the kitchen-scale task.
- Modify `services/lifeos-api/src/lifeos_api/schemas.py`: add `ProfileSettingsPatch`.
- Modify `services/lifeos-api/src/lifeos_api/main.py`: expose settings in `/profile`, contexts, and sport workout generation.
- Modify `services/lifeos-api/tests/test_api.py`: add TDD coverage for defaults, context exposure, patching, and personalized sport generation.
- Modify `openclaw/workspace/AGENTS.md`, `openclaw/workspace/skills/lifeos/SKILL.md`, and `openclaw/config/openclaw.template.json`: require using personalization settings.
- Modify `docs/openclaw-openclue-setup.md`: document personalized Sport behavior.

## Task 1: Store And Seed Personalization

**Files:**
- Modify: `services/lifeos-api/src/lifeos_api/models.py`
- Create: `services/lifeos-api/alembic/versions/0004_profile_settings.py`
- Modify: `services/lifeos-api/src/lifeos_api/seed.py`
- Test: `services/lifeos-api/tests/test_api.py`

- [ ] **Step 1: Write failing defaults test**

Add a test that calls `GET /profile` and expects `personalization.sport`, `personalization.food`, `personalization.daily`, and `personalization.coaching`.

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
cd services/lifeos-api
uv run pytest tests/test_api.py::test_profile_includes_seeded_personalization_settings -q
```

Expected: failure because `personalization` is missing.

- [ ] **Step 3: Add model, migration, and seed data**

Add a `ProfileSetting` model with `user_id`, `domain`, and JSON `settings`. Seed four domains: `sport`, `food`, `daily`, and `coaching`.

- [ ] **Step 4: Return settings from `/profile`**

Add helpers in `main.py` that read settings into a `{domain: settings}` dict and include it in `profile_to_dict`.

- [ ] **Step 5: Run the defaults test**

Expected: pass.

## Task 2: Context Exposure And Updates

**Files:**
- Modify: `services/lifeos-api/src/lifeos_api/schemas.py`
- Modify: `services/lifeos-api/src/lifeos_api/main.py`
- Test: `services/lifeos-api/tests/test_api.py`

- [ ] **Step 1: Write failing context/patch tests**

Add tests that:

- `GET /context/sport` exposes sport personalization.
- `GET /context/food` exposes food personalization.
- `GET /context/daily` exposes daily and coaching personalization.
- `PATCH /profile/settings/sport` can update a single setting without deleting the rest.

- [ ] **Step 2: Run the tests and verify they fail**

Run targeted pytest for the new tests.

- [ ] **Step 3: Add `ProfileSettingsPatch` and PATCH endpoint**

Add a permissive settings patch schema with a JSON object and merge updates into the domain settings.

- [ ] **Step 4: Add context filtering**

Expose only relevant personalization blocks in each context.

- [ ] **Step 5: Run targeted tests**

Expected: pass.

## Task 3: Personalize `/sport/today`

**Files:**
- Modify: `services/lifeos-api/src/lifeos_api/main.py`
- Test: `services/lifeos-api/tests/test_api.py`

- [ ] **Step 1: Write failing personalized sport tests**

Add tests that:

- City/pool context generates a swim workout with 50 m repeat guidance.
- City/gym context avoids lateral raises and includes full-body strength.
- Thursday grandparents day creates an easy recovery/bodyweight plan.
- Poor sleep notes reduce intensity.

- [ ] **Step 2: Run the tests and verify they fail**

Run targeted pytest for the new sport tests.

- [ ] **Step 3: Implement sport personalization helpers**

Use profile settings to choose modality, focus, intensity, and exercise list.

- [ ] **Step 4: Run targeted tests**

Expected: pass.

## Task 4: OpenClue Prompt And Docs

**Files:**
- Modify: `openclaw/workspace/AGENTS.md`
- Modify: `openclaw/workspace/skills/lifeos/SKILL.md`
- Modify: `openclaw/config/openclaw.template.json`
- Modify: `docs/openclaw-openclue-setup.md`
- Test: `services/lifeos-api/tests/test_api.py`

- [ ] **Step 1: Write failing prompt/docs test**

Assert prompts mention personalization settings, shoulder/lateral raise caution, strict food tracking, and city/home defaults.

- [ ] **Step 2: Update prompt/docs**

Route OpenClue to use `personalization` before making Sport/Food/Daily recommendations.

- [ ] **Step 3: Run prompt/docs test**

Expected: pass.

## Task 5: Verification And Commit

**Files:**
- All changed files.

- [ ] **Step 1: Run full API test suite**

```bash
cd services/lifeos-api
uv run pytest tests/test_api.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Validate OpenClaw config and Docker Compose**

```bash
python3 -m json.tool openclaw/config/openclaw.template.json >/tmp/openclaw-template.json
docker compose --env-file .env.example config >/tmp/lifeos-compose-config.yml
```

Expected: both commands exit 0.

- [ ] **Step 3: Run fresh migration smoke**

```bash
cd services/lifeos-api
rm -f /tmp/lifeos-personalization.db
DATABASE_URL=sqlite+pysqlite:////tmp/lifeos-personalization.db uv run alembic upgrade head
```

Expected: migrations through `0004_profile_settings` succeed.

- [ ] **Step 4: Commit**

```bash
git add services/lifeos-api openclaw docs
git commit -m "feat: add sport personalization"
```
