from __future__ import annotations

def test_health_daily_summary_upsert_and_context(tmp_path, make_client):
    with make_client(tmp_path) as client:
        first = client.post(
            "/health/daily-summaries",
            json={
                "summary_date": "2026-05-11",
                "source": "apple_health",
                "sleep_duration_minutes": 420,
                "sleep_quality": 82,
                "weight_kg": 117,
                "body_fat_percent": 34.5,
                "bmi": 38.2,
                "steps": 3200,
                "active_energy_kcal": 410,
                "workouts_count": 1,
                "resting_heart_rate": 62,
                "average_heart_rate": 91,
                "notes": "Initial wearable sync.",
            },
        )
        second = client.post(
            "/health/daily-summaries",
            json={
                "summary_date": "2026-05-11",
                "source": "apple_health",
                "weight_kg": 116.6,
                "steps": 4000,
                "notes": "Updated later.",
            },
        )
        sport_context = client.get("/context/sport")

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["weight_kg"] == 116.6
    assert second.json()["steps"] == 4000
    assert sport_context.json()["recent_health_summaries"][0]["id"] == first.json()["id"]

def test_health_progress_is_returned_for_sport_food_and_daily_contexts(tmp_path, make_client):
    with make_client(tmp_path) as client:
        for payload in [
            {
                "summary_date": "2026-05-09",
                "source": "apple_health",
                "weight_kg": 118.4,
                "body_fat_percent": 39.0,
                "bmi": 38.7,
                "steps": 3000,
                "active_energy_kcal": 300,
                "resting_heart_rate": 60,
                "average_heart_rate": 78,
            },
            {
                "summary_date": "2026-05-10",
                "source": "apple_health",
                "weight_kg": 118.0,
                "body_fat_percent": 38.8,
                "bmi": 38.6,
                "steps": 5000,
                "active_energy_kcal": 450,
                "resting_heart_rate": 58,
                "average_heart_rate": 75,
            },
            {
                "summary_date": "2026-05-11",
                "source": "apple_health",
                "weight_kg": 117.9,
                "body_fat_percent": 38.6,
                "bmi": 38.5,
                "steps": 5254,
                "active_energy_kcal": 509,
                "resting_heart_rate": 56,
                "average_heart_rate": 73,
                "notes": "iOS automatic health sync",
            },
        ]:
            response = client.post("/health/daily-summaries", json=payload)
            assert response.status_code in {200, 201}

        sport_context = client.get("/context/sport")
        food_context = client.get("/context/food")
        daily_context = client.get("/context/daily")

    for response in [sport_context, food_context, daily_context]:
        assert response.status_code == 200
        progress = response.json()["health_progress"]
        assert progress["latest"]["summary_date"] == "2026-05-11"
        assert progress["latest"]["metrics"]["weight_kg"] == 117.9
        assert progress["latest"]["metrics"]["steps"] == 5254
        assert progress["previous"]["summary_date"] == "2026-05-10"
        assert progress["deltas"]["weight_kg"] == -0.1
        assert progress["deltas"]["body_fat_percent"] == -0.2
        assert progress["deltas"]["steps"] == 254
        assert progress["seven_day_average"]["steps"] == 4418
        assert progress["seven_day_average"]["active_energy_kcal"] == 419.67
        assert progress["data_quality"]["summary_count"] == 3
        assert progress["data_quality"]["days_available"] == 3
        assert progress["data_quality"]["has_latest"] is True
        assert progress["data_quality"]["has_trend"] is True
        assert progress["data_quality"]["trend_status"] == "available"

def test_health_context_returns_direct_health_progress(tmp_path, make_client):
    with make_client(tmp_path) as client:
        response = client.post(
            "/health/daily-summaries",
            json={
                "summary_date": "2026-05-11",
                "source": "apple_health",
                "weight_kg": 117.9,
                "body_fat_percent": 38.6,
                "bmi": 38.5,
                "steps": 5254,
                "active_energy_kcal": 517,
                "resting_heart_rate": 56,
                "average_heart_rate": 73,
            },
        )
        context = client.get("/context/health")

    assert response.status_code == 201
    assert context.status_code == 200
    payload = context.json()
    assert payload["area"]["slug"] == "health"
    assert payload["profile"]["timezone"] == "Europe/Chisinau"
    assert payload["recent_health_summaries"][0]["summary_date"] == "2026-05-11"
    assert payload["health_progress"]["latest"]["metrics"]["weight_kg"] == 117.9
    assert payload["health_progress"]["latest"]["metrics"]["steps"] == 5254
    assert payload["health_progress"]["data_quality"]["trend_status"] == "needs_more_data"

def test_health_progress_uses_latest_update_for_same_day_source(tmp_path, make_client):
    with make_client(tmp_path) as client:
        first = client.post(
            "/health/daily-summaries",
            json={
                "summary_date": "2026-05-11",
                "source": "apple_health",
                "steps": 1000,
                "active_energy_kcal": 100,
            },
        )
        second = client.post(
            "/health/daily-summaries",
            json={
                "summary_date": "2026-05-11",
                "source": "apple_health",
                "steps": 6500,
                "active_energy_kcal": 620,
            },
        )
        context = client.get("/context/sport")

    assert first.status_code == 201
    assert second.status_code == 200
    assert context.status_code == 200
    progress = context.json()["health_progress"]
    assert progress["latest"]["id"] == first.json()["id"]
    assert progress["latest"]["metrics"]["steps"] == 6500
    assert progress["latest"]["metrics"]["active_energy_kcal"] == 620
    assert progress["previous"] is None
    assert progress["data_quality"]["has_trend"] is False
    assert progress["data_quality"]["trend_status"] == "needs_more_data"

def test_health_progress_handles_missing_metrics_without_crashing(tmp_path, make_client):
    with make_client(tmp_path) as client:
        response = client.post(
            "/health/daily-summaries",
            json={
                "summary_date": "2026-05-11",
                "source": "apple_health",
                "steps": 4000,
            },
        )
        context = client.get("/context/food")

    assert response.status_code == 201
    assert context.status_code == 200
    progress = context.json()["health_progress"]
    assert progress["latest"]["metrics"]["steps"] == 4000
    assert progress["latest"]["metrics"]["weight_kg"] is None
    assert progress["seven_day_average"]["steps"] == 4000
    assert progress["deltas"]["steps"] is None
    assert "weight_kg" in progress["data_quality"]["missing_latest_metrics"]
    assert "body_fat_percent" in progress["data_quality"]["missing_latest_metrics"]

def test_shortcut_health_ingestion_requires_shortcut_token(tmp_path, monkeypatch, make_client):
    monkeypatch.setenv("LIFEOS_SHORTCUT_TOKEN", "shortcut-token")
    with make_client(tmp_path) as client:
        normal_api_key_response = client.post(
            "/integrations/shortcuts/health-daily-summary",
            json={
                "summary_date": "2026-05-11",
                "source": "apple_health",
                "steps": 5200,
            },
        )
        wrong_token_response = client.post(
            "/integrations/shortcuts/health-daily-summary",
            headers={"Authorization": "Bearer wrong-token"},
            json={
                "summary_date": "2026-05-11",
                "source": "apple_health",
                "steps": 5200,
            },
        )

    assert normal_api_key_response.status_code == 401
    assert wrong_token_response.status_code == 401

def test_shortcut_health_ingestion_upserts_daily_summary(tmp_path, monkeypatch, make_client):
    monkeypatch.setenv("LIFEOS_SHORTCUT_TOKEN", "shortcut-token")
    with make_client(tmp_path) as client:
        first = client.post(
            "/integrations/shortcuts/health-daily-summary",
            headers={"Authorization": "Bearer shortcut-token"},
            json={
                "summary_date": "2026-05-11",
                "source": "apple_health",
                "sleep_duration_minutes": 430,
                "sleep_quality": 78,
                "weight_kg": 116.8,
                "body_fat_percent": 34.1,
                "bmi": 38.1,
                "steps": 5200,
                "active_energy_kcal": 490,
                "workouts_count": 1,
                "resting_heart_rate": 63,
                "average_heart_rate": 92,
            },
        )
        second = client.post(
            "/integrations/shortcuts/health-daily-summary",
            headers={"X-Shortcut-Token": "shortcut-token"},
            json={
                "summary_date": "2026-05-11",
                "source": "apple_health",
                "steps": 6000,
                "active_energy_kcal": 530,
            },
        )
        sport_context = client.get("/context/sport")

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["steps"] == 6000
    assert second.json()["active_energy_kcal"] == 530
    assert sport_context.json()["recent_health_summaries"][0]["id"] == first.json()["id"]
