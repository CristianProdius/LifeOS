from __future__ import annotations

from datetime import date, timedelta
import json
from importlib.resources import files

from fastapi.testclient import TestClient

def test_auth_requires_configured_key(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'auth-test.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("LIFEOS_API_KEY", "test-token")

    from lifeos_api.main import create_app

    app = create_app(database_url=database_url, seed_database=True)
    with TestClient(app) as client:
        unauthorized = client.get("/health")
        authorized = client.get("/health", headers={"X-API-Key": "test-token"})

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200

def test_health_reports_seeded_database(tmp_path, make_client):
    with make_client(tmp_path) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["database"] == "ok"
    assert response.json()["seeded"] is True

def test_seed_reset_plan_is_idempotent(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'seed-test.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    from lifeos_api.database import create_engine_and_session, init_database
    from lifeos_api.models import Area, TaskTemplate
    from lifeos_api.seed import seed_reset_plan

    engine, session_factory = create_engine_and_session(database_url)
    init_database(engine)

    with session_factory() as session:
        first = seed_reset_plan(session)
        second = seed_reset_plan(session)
        area_count = session.query(Area).count()
        template_count = session.query(TaskTemplate).count()

    assert first["created"] > 0
    assert second["created"] == 0
    assert area_count >= 7
    assert template_count == 14


def test_sport_program_seed_data_stays_internally_consistent():
    program = json.loads((files("lifeos_api.data") / "sport_program.json").read_text(encoding="utf-8"))
    start_date = date.fromisoformat(program["program"]["start_date"])
    weeks = program["weeks"]

    assert program["program"]["duration_weeks"] == len(weeks)
    assert weeks[0]["week_number"] == 1
    assert weeks[-1]["week_number"] == program["program"]["duration_weeks"]

    for index, week in enumerate(weeks, start=1):
        expected_start = start_date + timedelta(days=(index - 1) * 7)
        expected_end = expected_start + timedelta(days=6)

        assert week["week_number"] == index
        assert date.fromisoformat(week["week_start"]) == expected_start
        assert date.fromisoformat(week["week_end"]) == expected_end
        assert week["target_recovery_sessions"] >= 0
        assert week["target_strength_sessions"] >= 1
        assert week["target_cardio_sessions"] >= 1
        assert week["target_steps_avg"] <= 9000
