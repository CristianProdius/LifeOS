from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient


def make_client(tmp_path, monkeypatch) -> TestClient:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'lifeos-test.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("LIFEOS_API_KEY", "test-token")

    from lifeos_api.main import create_app

    app = create_app(database_url=database_url, seed_database=True)
    return TestClient(app, headers={"X-API-Key": "test-token"})


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


def test_health_reports_seeded_database(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
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


def test_tasks_can_be_created_patched_and_read_in_area_context(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        create_response = client.post(
            "/tasks",
            json={
                "title": "Close open loops",
                "area": "business",
                "priority": 4,
                "due_date": "2026-05-09",
                "notes": "Keep the scope short.",
            },
        )
        task_id = create_response.json()["id"]

        patch_response = client.patch(
            f"/tasks/{task_id}",
            json={"status": "done", "notes": "Finished in the morning block."},
        )
        context_response = client.get("/context/business")

    assert create_response.status_code == 201
    assert patch_response.status_code == 200
    assert patch_response.json()["status"] == "done"
    assert context_response.status_code == 200
    assert any(task["id"] == task_id for task in context_response.json()["tasks"])


def test_habit_log_is_upserted_by_habit_and_date(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        first = client.post(
            "/habits/log",
            json={
                "habit": "sleep",
                "log_date": "2026-05-08",
                "value": 7.5,
                "notes": "Good sleep window.",
            },
        )
        second = client.post(
            "/habits/log",
            json={
                "habit": "sleep",
                "log_date": "2026-05-08",
                "value": 8,
                "notes": "Adjusted after wearable sync.",
            },
        )

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["value"] == 8


def test_checkins_are_saved_with_area_context(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        checkin_response = client.post(
            "/checkins",
            json={
                "area": "review",
                "mood": 6,
                "energy": 5,
                "stress": 7,
                "notes": "Anxious but clear.",
            },
        )
        context_response = client.get("/context/review")

    assert checkin_response.status_code == 201
    assert checkin_response.json()["area"] == "review"
    assert context_response.json()["recent_checkins"][0]["notes"] == "Anxious but clear."


def test_workout_recommendation_and_log(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        recommendation = client.post(
            "/workouts/recommend",
            json={
                "goal": "strength",
                "available_minutes": 30,
                "equipment": ["dumbbells"],
                "intensity": "moderate",
            },
        )
        log_response = client.post(
            "/workouts/log",
            json={
                "session_date": "2026-05-08",
                "workout_type": "strength",
                "duration_minutes": 28,
                "intensity": "moderate",
                "notes": "Felt controlled.",
                "exercises": [
                    {"name": "Goblet squat", "sets": 3, "reps": 10, "weight": 22.5},
                    {"name": "Dumbbell row", "sets": 3, "reps": 12, "weight": 18},
                ],
            },
        )

    assert recommendation.status_code == 200
    assert recommendation.json()["available_minutes"] == 30
    assert len(recommendation.json()["exercises"]) >= 3
    assert log_response.status_code == 201
    assert len(log_response.json()["exercises"]) == 2


def test_profile_defaults_and_updates(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        default_profile = client.get("/profile")
        update_response = client.patch(
            "/profile",
            json={
                "default_context": "chisinau_gym",
                "equipment": {"walking_pad": "available", "pull_up_bar": "planned"},
            },
        )

    assert default_profile.status_code == 200
    assert default_profile.json()["timezone"] == "Europe/Chisinau"
    assert default_profile.json()["default_context"] == "grandparents_home"
    assert default_profile.json()["training_level"] == "beginner_returning"
    assert default_profile.json()["goals"] == ["fat_loss", "consistency", "run_later"]
    assert default_profile.json()["equipment"]["walking_pad"] == "planned"
    assert default_profile.json()["equipment"]["pull_up_bar"] == "planned"
    assert update_response.status_code == 200
    assert update_response.json()["default_context"] == "chisinau_gym"
    assert update_response.json()["equipment"]["walking_pad"] == "available"


def test_workout_plan_is_stored_and_contextualized_for_home(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        plan_response = client.post(
            "/workouts/plan",
            json={
                "plan_date": "2026-05-11",
                "goal": "fat_loss",
                "available_minutes": 35,
                "location_context": "grandparents_home",
                "equipment": [],
                "intensity": "easy",
                "telegram_metadata": {
                    "chat_id": "-1003943676064",
                    "topic_id": "5",
                    "message_id": "78",
                },
            },
        )
        context_response = client.get("/context/sport")

    assert plan_response.status_code == 201
    planned = plan_response.json()
    assert planned["status"] == "proposed"
    assert planned["location_context"] == "grandparents_home"
    assert planned["telegram_metadata"]["topic_id"] == "5"
    exercise_names = {exercise["name"].lower() for exercise in planned["exercises"]}
    assert "romanian deadlift" not in exercise_names
    assert any("walk" in name for name in exercise_names)
    assert context_response.status_code == 200
    assert context_response.json()["active_planned_workout"]["id"] == planned["id"]
    assert context_response.json()["profile"]["default_context"] == "grandparents_home"
    assert len(context_response.json()["recent_health_summaries"]) == 0


def test_workout_plan_complete_is_idempotent(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        plan_id = client.post(
            "/workouts/plan",
            json={
                "plan_date": "2026-05-11",
                "goal": "consistency",
                "available_minutes": 25,
                "location_context": "grandparents_home",
                "equipment": [],
            },
        ).json()["id"]
        started = client.patch(f"/workouts/plans/{plan_id}", json={"status": "started", "notes": "Started after lunch."})
        first_complete = client.post(f"/workouts/plans/{plan_id}/complete", json={"notes": "Finished controlled."})
        second_complete = client.post(f"/workouts/plans/{plan_id}/complete", json={"notes": "Duplicate Telegram click."})
        sport_context = client.get("/context/sport")

    assert started.status_code == 200
    assert started.json()["status"] == "started"
    assert first_complete.status_code == 200
    assert second_complete.status_code == 200
    assert first_complete.json()["status"] == "completed"
    assert first_complete.json()["completed_workout_id"] == second_complete.json()["completed_workout_id"]
    assert sport_context.json()["latest_workout"]["id"] == first_complete.json()["completed_workout_id"]


def test_workout_plan_can_be_read_after_callback_update(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        plan_id = client.post(
            "/workouts/plan",
            json={
                "plan_date": "2026-05-11",
                "goal": "fat_loss",
                "available_minutes": 20,
                "location_context": "grandparents_home",
                "equipment": [],
            },
        ).json()["id"]
        completed = client.post(f"/workouts/plans/{plan_id}/complete", json={})
        fetched = client.get(f"/workouts/plans/{plan_id}")

    assert completed.status_code == 200
    assert fetched.status_code == 200
    assert fetched.json()["id"] == plan_id
    assert fetched.json()["status"] == "completed"
    assert fetched.json()["completed_workout_id"] == completed.json()["completed_workout_id"]


def test_health_daily_summary_upsert_and_context(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
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


def test_health_progress_is_returned_for_sport_food_and_daily_contexts(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
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


def test_health_context_returns_direct_health_progress(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
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


def test_health_progress_uses_latest_update_for_same_day_source(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
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


def test_health_progress_handles_missing_metrics_without_crashing(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
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


def test_openclue_prompts_and_docs_reference_health_progress_contract():
    repo_root = Path(__file__).resolve().parents[3]
    agents = (repo_root / "openclaw/workspace/AGENTS.md").read_text()
    skill = (repo_root / "openclaw/workspace/skills/lifeos/SKILL.md").read_text()
    config = (repo_root / "openclaw/config/openclaw.template.json").read_text()
    shortcut_docs = (repo_root / "docs/shortcut-health-ingestion.md").read_text()

    for text in [agents, skill, config]:
        assert "health_progress" in text
        assert "/context/health" in text
        assert "Do not overreact to one bad day" in text
    assert '"thinkingDefault": "low"' in config
    assert '"fastModeDefault": true' in config
    assert "sleep_duration_minutes" not in shortcut_docs
    assert "workouts_count" not in shortcut_docs
    assert "Xiaomi scale" in shortcut_docs


def test_shortcut_health_ingestion_requires_shortcut_token(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFEOS_SHORTCUT_TOKEN", "shortcut-token")
    with make_client(tmp_path, monkeypatch) as client:
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


def test_shortcut_health_ingestion_upserts_daily_summary(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFEOS_SHORTCUT_TOKEN", "shortcut-token")
    with make_client(tmp_path, monkeypatch) as client:
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


def test_skipping_workout_plan_does_not_create_completed_workout(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        plan_id = client.post(
            "/workouts/plan",
            json={
                "plan_date": "2026-05-11",
                "goal": "fat_loss",
                "available_minutes": 20,
                "location_context": "grandparents_home",
                "equipment": [],
            },
        ).json()["id"]
        skipped = client.patch(f"/workouts/plans/{plan_id}", json={"status": "skipped", "notes": "Too tired."})
        sport_context = client.get("/context/sport")

    assert skipped.status_code == 200
    assert skipped.json()["status"] == "skipped"
    assert skipped.json()["completed_workout_id"] is None
    assert sport_context.json()["active_planned_workout"] is None
    assert sport_context.json()["latest_workout"] is None


def test_finance_import_summary_and_affordability(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        import_response = client.post(
            "/finance/import",
            json={
                "source": "manual-test",
                "rows": [
                    {
                        "date": "2026-05-01",
                        "description": "Paycheck",
                        "amount": 3000,
                        "category": "income",
                        "account": "checking",
                    },
                    {
                        "date": "2026-05-02",
                        "description": "Rent",
                        "amount": -1200,
                        "category": "car",
                        "account": "checking",
                    },
                    {
                        "date": "2026-05-03",
                        "description": "Groceries",
                        "amount": -220.45,
                        "category": "food",
                        "account": "checking",
                    },
                ],
            },
        )
        approve_response = client.post(f"/finance/import/{import_response.json()['id']}/approve", json={})
        duplicate_response = client.post(
            "/finance/import",
            json={
                "source": "manual-test",
                "rows": [
                    {
                        "date": "2026-05-01",
                        "description": "Paycheck",
                        "amount": 3000,
                        "category": "income",
                        "account": "checking",
                    }
                ],
            },
        )
        summary = client.get("/finance/summary")
        finance_alias = client.get("/finance")
        affordability = client.post(
            "/finance/affordability",
            json={
                "purchase_amount": 900,
                "monthly_income": 3000,
                "monthly_expenses": 1600,
                "current_savings": 250,
                "months": 3,
            },
        )

    assert import_response.status_code == 201
    assert import_response.json()["status"] == "review_pending"
    assert import_response.json()["staged"] == 3
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "complete"
    assert approve_response.json()["imported"] == 3
    assert {item["status"] for item in approve_response.json()["review_items"]} == {"approved"}
    assert duplicate_response.status_code == 201
    assert duplicate_response.json()["status"] == "review_pending"
    assert summary.status_code == 200
    assert finance_alias.status_code == 200
    assert summary.json()["income"] == 3000
    assert summary.json()["expenses"] == 1420.45
    assert summary.json()["net"] == 1579.55
    assert affordability.status_code == 200
    assert affordability.json()["affordable"] is True
    assert affordability.json()["monthly_savings_needed"] == 216.67


def test_finance_import_preserves_repeated_same_day_charges(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        import_response = client.post(
            "/finance/import",
            json={
                "source": "repeat-test",
                "rows": [
                    {"date": "2026-05-01", "description": "Coffee", "amount": -3.5, "account": "cash"},
                    {"date": "2026-05-01", "description": "Coffee", "amount": -3.5, "account": "cash"},
                ],
            },
        )
        approve_response = client.post(f"/finance/import/{import_response.json()['id']}/approve", json={})
        summary = client.get("/finance/summary")

    assert import_response.status_code == 201
    assert len({item["external_id"] for item in import_response.json()["review_items"]}) == 2
    assert approve_response.json()["imported"] == 2
    assert summary.json()["expenses"] == 7


def test_daily_plan_and_reviews_are_persisted(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as client:
        client.post(
            "/tasks",
            json={
                "title": "Plan recovery block",
                "area": "sport",
                "priority": 5,
                "due_date": str(date.today()),
            },
        )
        plan_response = client.post(
            "/daily/plan",
            json={
                "plan_date": str(date.today()),
                "focus_area": "sport",
                "capacity_minutes": 90,
            },
        )
        daily_review = client.post(
            "/reviews/daily",
            json={
                "review_date": str(date.today()),
                "wins": ["Trained", "Shipped API test"],
                "blockers": ["Context switching"],
                "mood": 7,
                "energy": 6,
                "notes": "Useful reset day.",
            },
        )
        weekly_review = client.post(
            "/reviews/weekly",
            json={
                "week_start": "2026-05-04",
                "wins": ["Stable sleep"],
                "lessons": ["Protect mornings"],
                "next_focus": ["Money", "Movement"],
                "score": 8,
            },
        )

    assert plan_response.status_code == 201
    assert plan_response.json()["focus_area"] == "sport"
    assert any("Plan recovery block" in task["title"] for task in plan_response.json()["tasks"])
    assert daily_review.status_code == 201
    assert daily_review.json()["mood"] == 7
    assert weekly_review.status_code == 201
    assert weekly_review.json()["score"] == 8
