from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def make_client(monkeypatch):
    def factory(tmp_path) -> TestClient:
        database_url = f"sqlite+pysqlite:///{tmp_path / 'lifeos-test.db'}"
        monkeypatch.setenv("DATABASE_URL", database_url)
        monkeypatch.setenv("LIFEOS_API_KEY", "test-token")

        from lifeos_api.main import create_app

        app = create_app(database_url=database_url, seed_database=True)
        return TestClient(app, headers={"X-API-Key": "test-token"})

    return factory
