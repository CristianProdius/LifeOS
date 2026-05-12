from __future__ import annotations

def test_tasks_can_be_created_patched_and_read_in_area_context(tmp_path, make_client):
    with make_client(tmp_path) as client:
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

def test_habit_log_is_upserted_by_habit_and_date(tmp_path, make_client):
    with make_client(tmp_path) as client:
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

def test_checkins_are_saved_with_area_context(tmp_path, make_client):
    with make_client(tmp_path) as client:
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

def test_profile_defaults_and_updates(tmp_path, make_client):
    with make_client(tmp_path) as client:
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

def test_profile_includes_seeded_personalization_settings(tmp_path, make_client):
    with make_client(tmp_path) as client:
        response = client.get("/profile")
        food_context = client.get("/context/food")

    assert response.status_code == 200
    personalization = response.json()["personalization"]
    assert personalization["sport"]["city_training_time"] == "morning"
    assert personalization["sport"]["home_training_time"] == "midday"
    assert personalization["sport"]["swimming_baseline"]["repeat_distance_m"] == 50
    assert "lateral_raises" in personalization["sport"]["exercise_restrictions"]["avoid"]
    assert personalization["food"]["tracking_mode"] == "strict_calories_protein"
    assert personalization["food"]["deficit_strategy"] == "aggressive_adjustable"
    assert personalization["daily"]["sleep"]["wake_target"] == "07:00"
    assert personalization["coaching"]["style"] == "strict_data_based"
    food_tasks = {task["title"] for task in food_context.json()["tasks"]}
    assert "Buy kitchen scale" in food_tasks

def test_contexts_expose_relevant_personalization_and_settings_patch_merges(tmp_path, make_client):
    with make_client(tmp_path) as client:
        patch_response = client.patch(
            "/profile/settings/sport",
            json={"settings": {"city_training_days": ["wednesday", "friday"], "home_training_time": "evening"}},
        )
        sport_context = client.get("/context/sport")
        food_context = client.get("/context/food")
        daily_context = client.get("/context/daily")

    assert patch_response.status_code == 200
    patched_sport = patch_response.json()
    assert patched_sport["city_training_days"] == ["wednesday", "friday"]
    assert patched_sport["home_training_time"] == "evening"
    assert patched_sport["swimming_baseline"]["repeat_distance_m"] == 50
    assert sport_context.json()["personalization"]["sport"]["home_training_time"] == "evening"
    assert sport_context.json()["personalization"]["coaching"]["style"] == "strict_data_based"
    assert food_context.json()["personalization"]["food"]["tracking_mode"] == "strict_calories_protein"
    assert "sport" not in food_context.json()["personalization"]
    assert daily_context.json()["personalization"]["daily"]["sleep"]["wake_target"] == "07:00"
    assert daily_context.json()["personalization"]["coaching"]["failure_triggers"][0] == "sleep_snooze_loop"

