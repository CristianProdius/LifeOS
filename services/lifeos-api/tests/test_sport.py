from __future__ import annotations

def test_sport_program_seed_is_idempotent_and_visible(tmp_path, make_client):
    with make_client(tmp_path) as client:
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

def test_workout_recommendation_and_log(tmp_path, make_client):
    with make_client(tmp_path) as client:
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

def test_workout_plan_is_stored_and_contextualized_for_home(tmp_path, make_client):
    with make_client(tmp_path) as client:
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

def test_workout_plan_complete_is_idempotent(tmp_path, make_client):
    with make_client(tmp_path) as client:
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

def test_workout_plan_can_be_read_after_callback_update(tmp_path, make_client):
    with make_client(tmp_path) as client:
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

def test_sport_progress_reports_low_confidence_with_sparse_data(tmp_path, make_client):
    with make_client(tmp_path) as client:
        response = client.get("/sport/progress")

    assert response.status_code == 200
    payload = response.json()
    assert payload["goal"]["target_weight_kg"] == 90
    assert payload["stretch"]["weight_kg"] == 95
    assert payload["confidence"] == "low"
    assert 0 <= payload["on_track_score"] <= 100
    assert any("weight trend" in reason.lower() for reason in payload["reasons"])

def test_sport_progress_stays_low_confidence_without_weight_trend(tmp_path, make_client):
    with make_client(tmp_path) as client:
        for day in range(5, 12):
            response = client.post(
                "/health/daily-summaries",
                json={
                    "summary_date": f"2026-05-{day:02d}",
                    "source": "apple_health",
                    "steps": 5500,
                    "active_energy_kcal": 420,
                },
            )
            assert response.status_code in {200, 201}

        first_plan = client.post("/sport/today", json={"request_date": "2026-05-11", "location_context": "grandparents_home"})
        second_plan = client.post("/sport/today", json={"request_date": "2026-05-12", "location_context": "grandparents_home"})
        assert first_plan.status_code == 201
        assert second_plan.status_code == 201
        assert client.post(f"/workouts/plans/{first_plan.json()['planned_workout']['id']}/complete", json={}).status_code == 200
        assert client.post(f"/workouts/plans/{second_plan.json()['planned_workout']['id']}/complete", json={}).status_code == 200

        progress = client.get("/sport/progress")

    assert progress.status_code == 200
    payload = progress.json()
    assert payload["latest_weight_kg"] is None
    assert payload["confidence"] == "low"
    assert payload["health_progress"]["data_quality"]["metric_days_available"]["weight_kg"] == 0
    assert any("daily weight" in reason.lower() for reason in payload["reasons"])

def test_sport_today_creates_program_linked_home_workout_idempotently(tmp_path, make_client):
    with make_client(tmp_path) as client:
        first = client.post("/sport/today", json={"request_date": "2026-05-11", "location_context": "grandparents_home"})
        second = client.post("/sport/today", json={"request_date": "2026-05-11", "location_context": "grandparents_home"})
        from lifeos_api.models import AdviceLog

        with client.app.state.session_factory() as session:
            advice = session.query(AdviceLog).filter(AdviceLog.advice_type == "sport_today").one()
            advice_output = advice.output_payload

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
    assert "T" in advice_output["planned_workout"]["created_at"]

def test_sport_today_gym_context_differs_from_home(tmp_path, make_client):
    with make_client(tmp_path) as client:
        response = client.post("/sport/today", json={"request_date": "2026-05-12", "location_context": "chisinau_gym"})

    assert response.status_code == 201
    names = {exercise["name"].lower() for exercise in response.json()["planned_workout"]["exercises"]}
    assert any("press" in name or "pulldown" in name or "bike" in name for name in names)

def test_sport_today_uses_swim_baseline_for_pool_context(tmp_path, make_client):
    with make_client(tmp_path) as client:
        response = client.post("/sport/today", json={"request_date": "2026-05-13", "location_context": "chisinau_pool"})

    assert response.status_code == 201
    planned = response.json()["planned_workout"]
    exercise_text = " ".join(f"{exercise['name']} {exercise.get('notes', '')}" for exercise in planned["exercises"]).lower()
    assert planned["duration_minutes"] == 60
    assert planned["adaptation_reason"].endswith("swim_low_impact")
    assert "50 m" in exercise_text
    assert "20 seconds" in exercise_text

def test_sport_today_uses_gym_full_body_without_lateral_raises(tmp_path, make_client):
    with make_client(tmp_path) as client:
        response = client.post("/sport/today", json={"request_date": "2026-05-15", "location_context": "chisinau_gym"})

    assert response.status_code == 201
    planned = response.json()["planned_workout"]
    names = {exercise["name"].lower() for exercise in planned["exercises"]}
    assert planned["duration_minutes"] == 60
    assert planned["adaptation_reason"].endswith("gym_full_body")
    assert "lateral raise" not in " ".join(names)
    assert any("goblet" in name or "leg press" in name for name in names)
    assert any("row" in name or "pulldown" in name for name in names)

def test_sport_today_uses_grandparents_midday_home_plan(tmp_path, make_client):
    with make_client(tmp_path) as client:
        response = client.post("/sport/today", json={"request_date": "2026-05-14", "location_context": "grandparents_home"})

    assert response.status_code == 201
    planned = response.json()["planned_workout"]
    names = {exercise["name"].lower() for exercise in planned["exercises"]}
    assert planned["duration_minutes"] == 40
    assert planned["adaptation_reason"].endswith("home_midday_bodyweight")
    assert any("pull" in name or "dead hang" in name for name in names)
    assert "leg press" not in names

def test_sport_today_reduces_intensity_after_poor_sleep_note(tmp_path, make_client):
    with make_client(tmp_path) as client:
        response = client.post(
            "/sport/today",
            json={"request_date": "2026-05-18", "location_context": "chisinau_gym", "notes": "Slept 4 hours and feel tired."},
        )

    assert response.status_code == 201
    planned = response.json()["planned_workout"]
    assert planned["intensity"] == "easy"
    assert planned["duration_minutes"] <= 40
    assert "poor_sleep" in planned["adaptation_reason"]
    names = {exercise["name"].lower() for exercise in planned["exercises"]}
    assert any("walk" in name or "mobility" in name for name in names)

def test_sport_missed_day_creates_safe_adjustment(tmp_path, make_client):
    with make_client(tmp_path) as client:
        plan = client.post("/sport/today", json={"request_date": "2026-05-11", "location_context": "grandparents_home"})
        response = client.post("/sport/missed-day", json={"missed_date": "2026-05-11", "reason": "travel"})
        progress = client.get("/sport/progress")
        context = client.get("/sport/program/active")

    assert plan.status_code == 201
    assert response.status_code == 201
    payload = response.json()
    assert payload["adjustment"]["reason"] == "missed_workout"
    assert payload["skipped_plan"]["status"] == "skipped"
    assert progress.json()["weekly_adherence"]["skipped_sessions"] == 1
    assert context.json()["next_planned_workout"] is None
    assert "easy" in " ".join(payload["next_actions"]).lower()
    assert progress.status_code == 200

def test_skipping_workout_plan_does_not_create_completed_workout(tmp_path, make_client):
    with make_client(tmp_path) as client:
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

