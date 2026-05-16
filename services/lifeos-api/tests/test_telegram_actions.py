from __future__ import annotations

from datetime import date


def test_food_action_buttons_confirm_patch_and_delete_logs(tmp_path, make_client):
    with make_client(tmp_path) as client:
        created = client.post(
            "/food/logs",
            json={
                "log_date": "2026-05-12",
                "meal_type": "lunch",
                "source": "telegram_photo",
                "description": "Chicken and potatoes estimate",
                "calories": 620,
                "protein_g": 38,
                "confidence": "estimated",
            },
        )
        food_log_id = created.json()["id"]

        confirmed = client.post(
            "/telegram/actions",
            json={
                "callback_data": f"lifeos:food:{food_log_id}:looks_right",
                "metadata": {"callback_id": "food-confirm-1", "topic_id": "9"},
            },
        )
        edited = client.post(
            "/telegram/actions",
            json={
                "callback_data": f"lifeos:food:{food_log_id}:edit_calories",
                "value": 700,
                "metadata": {"callback_id": "food-calories-1", "topic_id": "9"},
            },
        )
        deleted = client.post(
            "/telegram/actions",
            json={
                "callback_data": f"lifeos:food:{food_log_id}:delete",
                "metadata": {"callback_id": "food-delete-1", "topic_id": "9"},
            },
        )
        summary = client.get("/food/daily-summary", params={"summary_date": "2026-05-12"})

    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "saved"
    assert confirmed.json()["resource"]["confidence"] == "confirmed_estimate"
    assert edited.status_code == 200
    assert edited.json()["resource"]["calories"] == 700
    assert deleted.status_code == 200
    assert deleted.json()["resource"]["status"] == "deleted"
    assert summary.json()["totals"]["calories"] == 0


def test_repeated_food_confirm_suppresses_visible_reply(tmp_path, make_client):
    with make_client(tmp_path) as client:
        food_log_id = client.post(
            "/food/logs",
            json={
                "log_date": "2026-05-12",
                "meal_type": "add-on",
                "source": "telegram_text",
                "description": "Honey, 12 g",
                "calories": 36,
                "protein_g": 0,
                "confidence": "estimated",
            },
        ).json()["id"]

        first = client.post(
            "/telegram/actions",
            json={"callback_data": f"lifeos:food:{food_log_id}:looks_right"},
        )
        second = client.post(
            "/telegram/actions",
            json={"callback_data": f"lifeos:food:{food_log_id}:looks_right"},
        )

    assert first.status_code == 200
    assert first.json()["status"] == "saved"
    assert first.json()["suppress_visible_reply"] is False
    assert second.status_code == 200
    assert second.json()["status"] == "already_applied"
    assert second.json()["suppress_visible_reply"] is True
    assert second.json()["acknowledgement"] == "Already confirmed."


def test_openclue_legacy_food_callback_order_is_accepted(tmp_path, make_client):
    with make_client(tmp_path) as client:
        food_log_id = client.post(
            "/food/logs",
            json={
                "log_date": "2026-05-16",
                "meal_type": "snack",
                "source": "telegram_text",
                "description": "1 boiled egg white",
                "calories": 17,
                "protein_g": 4,
                "confidence": "estimated",
            },
        ).json()["id"]

        response = client.post(
            "/telegram/actions",
            json={"callback_data": f"food:looks_right:{food_log_id}"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "saved"
    assert response.json()["resource"]["confidence"] == "confirmed_estimate"


def test_food_action_buttons_can_request_missing_correction_value(tmp_path, make_client):
    with make_client(tmp_path) as client:
        food_log_id = client.post(
            "/food/logs",
            json={
                "log_date": "2026-05-12",
                "meal_type": "snack",
                "source": "telegram_photo",
                "description": "Protein yogurt estimate",
                "calories": 180,
                "protein_g": 20,
                "confidence": "estimated",
            },
        ).json()["id"]

        response = client.post(
            "/telegram/actions",
            json={"callback_data": f"lifeos:food:{food_log_id}:add_protein"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "needs_input"
    assert response.json()["requires_input"] is True
    assert response.json()["resource"]["telegram_metadata"]["pending_correction"] == "protein_g"


def test_workout_action_buttons_are_idempotent(tmp_path, make_client):
    with make_client(tmp_path) as client:
        plan_id = client.post(
            "/workouts/plan",
            json={
                "plan_date": "2026-05-12",
                "goal": "fat_loss",
                "available_minutes": 30,
                "location_context": "grandparents_home",
            },
        ).json()["id"]

        started = client.post("/telegram/actions", json={"callback_data": f"lifeos:workout:{plan_id}:start"})
        first_done = client.post("/telegram/actions", json={"callback_data": f"lifeos:workout:{plan_id}:done"})
        second_done = client.post("/telegram/actions", json={"callback_data": f"lifeos:workout:{plan_id}:done"})

    assert started.status_code == 200
    assert started.json()["resource"]["status"] == "started"
    assert first_done.status_code == 200
    assert first_done.json()["resource"]["status"] == "completed"
    assert second_done.status_code == 200
    assert second_done.json()["resource"]["completed_workout_id"] == first_done.json()["resource"]["completed_workout_id"]


def test_task_and_habit_action_buttons_update_lifeos(tmp_path, make_client):
    with make_client(tmp_path) as client:
        task_id = client.post(
            "/tasks",
            json={
                "title": "Ship one business deliverable",
                "area": "business",
                "priority": 5,
                "due_date": "2026-05-12",
            },
        ).json()["id"]
        habit_context = client.get("/context/daily").json()
        habit_id = next(habit["id"] for habit in habit_context["habits"] if habit["slug"] == "no-phone-in-bed")

        done_task = client.post(
            "/telegram/actions",
            json={"callback_data": f"lifeos:task:{task_id}:done", "action_date": "2026-05-12"},
        )
        habit_done = client.post(
            "/telegram/actions",
            json={"callback_data": f"lifeos:habit:{habit_id}:done", "action_date": "2026-05-12"},
        )
        snoozed_task = client.post(
            "/telegram/actions",
            json={"callback_data": f"lifeos:task:{task_id}:snooze_tomorrow", "action_date": "2026-05-12"},
        )

    assert done_task.status_code == 200
    assert done_task.json()["resource"]["status"] == "done"
    assert habit_done.status_code == 200
    assert habit_done.json()["resource"]["id"] is not None
    assert habit_done.json()["resource"]["value"] == 1
    assert snoozed_task.status_code == 200
    assert snoozed_task.json()["resource"]["status"] == "todo"
    assert snoozed_task.json()["resource"]["due_date"] == date(2026, 5, 13).isoformat()


def test_task_done_action_preserves_existing_completion_time(tmp_path, make_client):
    with make_client(tmp_path) as client:
        task_id = client.post(
            "/tasks",
            json={
                "title": "Do the thing once",
                "area": "daily",
                "priority": 3,
                "due_date": "2026-05-12",
            },
        ).json()["id"]

        first = client.post("/telegram/actions", json={"callback_data": f"lifeos:task:{task_id}:done"})
        second = client.post("/telegram/actions", json={"callback_data": f"lifeos:task:{task_id}:done"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["resource"]["completed_at"] == first.json()["resource"]["completed_at"]


def test_invalid_telegram_action_is_rejected(tmp_path, make_client):
    with make_client(tmp_path) as client:
        response = client.post("/telegram/actions", json={"callback_data": "bad-format"})

    assert response.status_code == 422
    assert response.json()["detail"] == "invalid callback data"
