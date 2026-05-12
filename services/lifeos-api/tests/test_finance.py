from __future__ import annotations

def test_finance_import_summary_and_affordability(tmp_path, make_client):
    with make_client(tmp_path) as client:
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

def test_finance_import_preserves_repeated_same_day_charges(tmp_path, make_client):
    with make_client(tmp_path) as client:
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

