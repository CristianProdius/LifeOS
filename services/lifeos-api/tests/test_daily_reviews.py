from __future__ import annotations

from datetime import date

def test_daily_plan_and_reviews_are_persisted(tmp_path, make_client):
    with make_client(tmp_path) as client:
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

