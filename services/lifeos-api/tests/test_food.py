from __future__ import annotations

from datetime import date

def test_food_target_uses_latest_weight_and_default_cut_targets(tmp_path, make_client):
    with make_client(tmp_path) as client:
        health_response = client.post(
            "/health/daily-summaries",
            json={
                "summary_date": "2026-05-11",
                "source": "apple_health",
                "weight_kg": 117,
                "body_fat_percent": 38.6,
                "bmi": 38.2,
            },
        )
        target_response = client.get("/food/target")

    assert health_response.status_code == 201
    assert target_response.status_code == 200
    target = target_response.json()
    assert target["status"] == "active"
    assert target["calories"] == 1900
    assert target["protein_g"] == 150
    assert target["calorie_floor"] == 1800
    assert target["calculation"]["formula"] == "mifflin_st_jeor"
    assert target["calculation"]["inputs"]["sex"] == "male"
    assert target["calculation"]["inputs"]["age_years"] == 23
    assert target["calculation"]["inputs"]["height_cm"] == 175
    assert target["calculation"]["inputs"]["weight_kg"] == 117
    assert target["calculation"]["bmr_kcal"] == 2154
    assert target["calculation"]["estimated_tdee_kcal"] == 2692

def test_food_logs_daily_summary_patch_and_delete(tmp_path, make_client):
    with make_client(tmp_path) as client:
        log_response = client.post(
            "/food/logs",
            json={
                "log_date": "2026-05-11",
                "meal_type": "breakfast",
                "source": "telegram_manual",
                "description": "Greek yogurt, eggs, and fruit",
                "calories": 650,
                "protein_g": 55,
                "carbs_g": 58,
                "fat_g": 22,
                "confidence": "estimated",
                "telegram_metadata": {"chat_id": "-1003943676064", "topic_id": "9"},
                "items": [
                    {"name": "Greek yogurt", "quantity": 250, "unit": "g", "calories": 220, "protein_g": 25},
                    {"name": "Eggs", "quantity": 3, "unit": "pieces", "calories": 240, "protein_g": 18},
                ],
                "notes": "Photo estimate.",
            },
        )
        log_id = log_response.json()["id"]
        patched = client.patch(f"/food/logs/{log_id}", json={"calories": 700, "protein_g": 60, "notes": "Corrected label."})
        summary = client.get("/food/daily-summary", params={"summary_date": "2026-05-11"})
        deleted = client.patch(f"/food/logs/{log_id}", json={"status": "deleted"})
        empty_summary = client.get("/food/daily-summary", params={"summary_date": "2026-05-11"})

    assert log_response.status_code == 201
    assert log_response.json()["items"][0]["name"] == "Greek yogurt"
    assert patched.status_code == 200
    assert patched.json()["calories"] == 700
    assert patched.json()["protein_g"] == 60
    assert summary.status_code == 200
    assert summary.json()["totals"]["calories"] == 700
    assert summary.json()["totals"]["protein_g"] == 60
    assert summary.json()["remaining"]["calories"] == 1200
    assert summary.json()["remaining"]["protein_g"] == 90
    assert summary.json()["adherence"]["calorie_status"] == "under_target"
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"
    assert empty_summary.json()["totals"]["calories"] == 0
    assert empty_summary.json()["data_quality"]["logged_meals"] == 0

def test_food_progress_adjusts_only_when_enough_food_and_weight_data(tmp_path, make_client):
    with make_client(tmp_path) as client:
        sparse_progress = client.get("/food/progress")
        for payload in [
            {"summary_date": "2026-05-09", "source": "apple_health", "weight_kg": 117.0},
            {"summary_date": "2026-05-10", "source": "apple_health", "weight_kg": 116.98},
            {"summary_date": "2026-05-11", "source": "apple_health", "weight_kg": 116.96},
        ]:
            assert client.post("/health/daily-summaries", json=payload).status_code in {200, 201}
        for day in range(7, 12):
            assert client.post(
                "/food/logs",
                json={
                    "log_date": f"2026-05-{day:02d}",
                    "meal_type": "day_total",
                    "source": "manual_total",
                    "description": "Daily total",
                    "calories": 1880,
                    "protein_g": 152,
                    "confidence": "exact",
                },
            ).status_code == 201
        progress = client.get("/food/progress", params={"reference_date": "2026-05-11"})

    assert sparse_progress.status_code == 200
    assert sparse_progress.json()["data_quality"]["enough_data_for_adjustment"] is False
    assert sparse_progress.json()["adjustment"]["action"] == "no_adjustment_insufficient_data"
    assert progress.status_code == 200
    payload = progress.json()
    assert payload["data_quality"]["logged_food_days"] == 5
    assert payload["data_quality"]["weight_entries"] == 3
    assert payload["data_quality"]["enough_data_for_adjustment"] is True
    assert payload["averages"]["calories"] == 1880
    assert payload["averages"]["protein_g"] == 152
    assert payload["adherence"]["calorie_adherence_rate"] == 1
    assert payload["weight_trend"]["latest_weight_kg"] == 116.96
    assert payload["weight_trend"]["delta_kg"] == -0.04
    assert payload["adjustment"]["action"] == "reduce_calories_by_100"
    assert payload["adjustment"]["next_calories"] == 1800

def test_food_context_includes_target_summary_and_progress(tmp_path, make_client):
    with make_client(tmp_path) as client:
        assert client.post(
            "/food/logs",
            json={
                "log_date": str(date.today()),
                "meal_type": "lunch",
                "source": "telegram_manual",
                "description": "Chicken salad",
                "calories": 520,
                "protein_g": 48,
                "confidence": "estimated",
            },
        ).status_code == 201
        context_response = client.get("/context/food")

    assert context_response.status_code == 200
    context = context_response.json()
    assert context["food_target"]["calories"] == 1900
    assert context["today_food_summary"]["totals"]["calories"] == 520
    assert context["today_food_summary"]["remaining"]["protein_g"] == 102
    assert context["food_progress"]["target"]["protein_g"] == 150
    assert context["food_progress"]["data_quality"]["logged_food_days"] == 1

