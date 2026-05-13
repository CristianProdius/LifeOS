from __future__ import annotations


def test_daily_command_center_returns_four_mandatory_commitments(tmp_path, make_client):
    with make_client(tmp_path) as client:
        business_task = client.post(
            "/tasks",
            json={
                "title": "Build NGO landing page draft",
                "area": "business",
                "priority": 5,
                "due_date": "2026-05-12",
            },
        )
        client.post(
            "/health/daily-summaries",
            json={
                "summary_date": "2026-05-12",
                "source": "apple_health",
                "steps": 1200,
                "active_energy_kcal": 220,
                "weight_kg": 117,
            },
        )

        response = client.post(
            "/daily/command-center",
            json={"plan_date": "2026-05-12", "capacity_minutes": 180},
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["plan_date"] == "2026-05-12"
    assert len(payload["mandatory_commitments"]) == 4
    assert [item["slot"] for item in payload["mandatory_commitments"]] == [
        "health",
        "business",
        "anti_distraction",
        "admin_review",
    ]
    assert payload["daily_plan"]["id"] is not None
    assert payload["scorecard"]["total"] == 4
    assert payload["health_sync"]["synced"] is True
    assert any(
        button["value"].startswith("lifeos:task:")
        for item in payload["mandatory_commitments"]
        for button in item["buttons"]
    )
    business_commitment = next(item for item in payload["mandatory_commitments"] if item["slot"] == "business")
    assert business_commitment["task"]["id"] == business_task.json()["id"]


def test_daily_command_center_reuses_existing_plan_for_same_day(tmp_path, make_client):
    with make_client(tmp_path) as client:
        first = client.post("/daily/command-center", json={"plan_date": "2026-05-12"})
        second = client.post("/daily/command-center", json={"plan_date": "2026-05-12"})

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["daily_plan"]["id"] == first.json()["daily_plan"]["id"]
    assert len(second.json()["mandatory_commitments"]) == 4


def test_daily_command_center_keeps_same_commitments_after_completion(tmp_path, make_client):
    with make_client(tmp_path) as client:
        first = client.post(
            "/daily/command-center",
            json={"plan_date": "2026-05-12", "capacity_minutes": 180},
        ).json()
        business = next(item for item in first["mandatory_commitments"] if item["slot"] == "business")

        done = client.post(
            "/telegram/actions",
            json={
                "callback_data": f"lifeos:task:{business['task']['id']}:done",
                "action_date": "2026-05-12",
            },
        )
        second = client.post(
            "/daily/command-center",
            json={"plan_date": "2026-05-12", "capacity_minutes": 180},
        )

    second_payload = second.json()
    second_business = next(item for item in second_payload["mandatory_commitments"] if item["slot"] == "business")
    assert done.status_code == 200
    assert second.status_code == 200
    assert second_business["task"]["id"] == business["task"]["id"]
    assert second_business["task"]["status"] == "done"
    assert second_payload["scorecard"]["completed"] == 1


def test_daily_command_center_reuses_existing_slot_tasks(tmp_path, make_client):
    with make_client(tmp_path) as client:
        health_task = client.post(
            "/tasks",
            json={
                "title": "Take 30 minute walk",
                "area": "health",
                "priority": 5,
                "due_date": "2026-05-12",
            },
        ).json()
        admin_task = client.post(
            "/tasks",
            json={
                "title": "Review today and prepare tomorrow",
                "area": "admin",
                "priority": 4,
                "due_date": "2026-05-12",
            },
        ).json()

        response = client.post("/daily/command-center", json={"plan_date": "2026-05-12"})

    payload = response.json()
    health = next(item for item in payload["mandatory_commitments"] if item["slot"] == "health")
    admin = next(item for item in payload["mandatory_commitments"] if item["slot"] == "admin_review")
    assert health["task"]["id"] == health_task["id"]
    assert admin["task"]["id"] == admin_task["id"]


def test_daily_command_center_ignores_non_command_center_daily_plan_snapshot(tmp_path, make_client):
    with make_client(tmp_path) as client:
        for index in range(4):
            client.post(
                "/tasks",
                json={
                    "title": f"Custom focus task {index}",
                    "area": "custom-focus",
                    "priority": 5 - index,
                    "due_date": "2026-05-12",
                },
            )
        daily_plan = client.post(
            "/daily/plan",
            json={"plan_date": "2026-05-12", "focus_area": "custom-focus"},
        )

        command_center = client.post("/daily/command-center", json={"plan_date": "2026-05-12"})

    assert daily_plan.status_code == 201
    assert len(daily_plan.json()["tasks"]) == 4
    payload = command_center.json()
    assert command_center.status_code == 200
    assert [item["slot"] for item in payload["mandatory_commitments"]] == [
        "health",
        "business",
        "anti_distraction",
        "admin_review",
    ]
    assert payload["mandatory_commitments"][0]["area"] == "health"
    assert payload["mandatory_commitments"][1]["area"] == "business"
    assert {item["area"] for item in payload["mandatory_commitments"]} != {"custom-focus"}
