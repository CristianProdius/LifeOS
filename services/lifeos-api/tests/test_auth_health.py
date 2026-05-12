from __future__ import annotations

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
