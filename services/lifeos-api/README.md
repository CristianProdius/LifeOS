# LifeOS API

FastAPI service for the OpenClue LifeOS backend. It uses SQLAlchemy 2, Alembic, Pydantic v2, and Postgres through psycopg. Tests run against SQLite so they do not require a local Postgres instance.

## Environment

- `DATABASE_URL`: SQLAlchemy database URL. Use `postgresql+psycopg://...` for Postgres. Plain `postgresql://...` and `postgres://...` are normalized to psycopg.
- `LIFEOS_API_KEY`: required API key. Clients must send `X-API-Key`. Tests may set `LIFEOS_ALLOW_ANONYMOUS=true` for isolated local cases.
- `LIFEOS_AUTO_CREATE_SCHEMA`: optional local-only escape hatch. SQLite auto-creates schema; Postgres should use Alembic migrations.

## Local Development

```bash
uv run --python 3.12 pytest
LIFEOS_API_KEY=local-dev-key uv run --python 3.12 uvicorn lifeos_api.main:create_app --factory --reload --port 8080
```

The app initializes tables on startup for local pragmatism and runs the idempotent 14-day reset seed when using `create_app()`.

## Migrations

```bash
DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/lifeos uv run --python 3.12 alembic upgrade head
```

The first migration creates the full v1 schema:

- users and areas
- life profile
- tasks and task templates
- habit definitions and logs
- checkins
- workout sessions and exercises
- planned workouts
- health daily summaries
- finance accounts, transactions, categories, budgets, goals, and imports
- uploaded files
- daily plans, daily reviews, weekly reviews
- advice logs

## Docker

```bash
docker build -t lifeos-api .
docker run --rm -p 8080:8080 -e PORT=8080 -e LIFEOS_API_KEY=replace-me -e DATABASE_URL=postgresql+psycopg://user:pass@host.docker.internal:5432/lifeos lifeos-api
```

## Endpoints

- `GET /health`
- `GET /profile`
- `PATCH /profile`
- `GET /context/{area}`
- `POST /checkins`
- `POST /tasks`
- `PATCH /tasks/{id}`
- `POST /habits/log`
- `POST /sport/program/seed`
- `GET /sport/program/active`
- `POST /sport/today`
- `GET /sport/progress`
- `POST /sport/missed-day`
- `POST /workouts/recommend` (legacy unsaved draft route)
- `POST /workouts/log`
- `POST /workouts/plan` (low-level/manual stored workout route)
- `GET /workouts/plans/{id}`
- `PATCH /workouts/plans/{id}`
- `POST /workouts/plans/{id}/complete`
- `POST /health/daily-summaries`
- `POST /finance/import`
- `POST /finance/import/{id}/approve`
- `POST /finance/import/{id}/reject`
- `GET /finance`
- `GET /finance/summary`
- `POST /finance/affordability`
- `POST /daily/plan`
- `POST /reviews/daily`
- `POST /reviews/weekly`
