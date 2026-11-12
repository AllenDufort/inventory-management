"""
Tests for restocking API endpoints.
"""
import pytest

import main


@pytest.fixture(autouse=True)
def clear_restock_orders():
    """Keep tests independent: reset the in-memory order store."""
    main.restock_orders.clear()
    yield
    main.restock_orders.clear()


def _order_payload(client, budget):
    rec = client.get(f"/api/restocking/recommendations?budget={budget}").json()
    return {
        "budget": budget,
        "items": [
            {"item_sku": i["item_sku"], "quantity": i["quantity"]}
            for i in rec["items"]
        ],
    }


class TestRestockingRecommendations:
    """Test suite for restocking recommendations."""

    def test_recommendations_structure(self, client):
        """Test recommendation response structure."""
        response = client.get("/api/restocking/recommendations?budget=5000")
        assert response.status_code == 200

        data = response.json()
        assert data["budget"] == 5000
        assert isinstance(data["items"], list)
        assert len(data["items"]) > 0

        for item in data["items"]:
            for field in ["item_sku", "item_name", "trend", "demand_gap",
                          "quantity", "unit_cost", "line_total", "lead_time_days"]:
                assert field in item
            assert isinstance(item["quantity"], int)
            assert isinstance(item["lead_time_days"], int)

    def test_recommendations_within_budget(self, client):
        """Test total cost never exceeds the budget."""
        for budget in [0, 50, 500, 2000, 5000, 100000]:
            data = client.get(f"/api/restocking/recommendations?budget={budget}").json()
            assert data["total_cost"] <= budget
            assert abs(data["remaining_budget"] - (budget - data["total_cost"])) < 0.01

    def test_recommendations_total_calculation(self, client):
        """Test total_cost equals sum of line totals and line totals are correct."""
        data = client.get("/api/restocking/recommendations?budget=5000").json()
        for item in data["items"]:
            assert abs(item["line_total"] - item["quantity"] * item["unit_cost"]) < 0.01
        assert abs(data["total_cost"] - sum(i["line_total"] for i in data["items"])) < 0.01

    def test_recommendations_zero_budget(self, client):
        """Test a zero budget recommends nothing."""
        data = client.get("/api/restocking/recommendations?budget=0").json()
        assert data["items"] == []
        assert data["total_cost"] == 0

    def test_recommendations_only_positive_gap_items(self, client):
        """Test decreasing-demand items are never recommended."""
        data = client.get("/api/restocking/recommendations?budget=100000").json()
        skus = [i["item_sku"] for i in data["items"]]
        assert "MTR-304" not in skus
        for item in data["items"]:
            assert item["demand_gap"] > 0
            assert item["quantity"] <= item["demand_gap"]

    def test_recommendations_priority_order(self, client):
        """Test increasing-trend items come before stable ones."""
        data = client.get("/api/restocking/recommendations?budget=100000").json()
        trends = [i["trend"] for i in data["items"]]
        last_increasing = max(i for i, t in enumerate(trends) if t == "increasing")
        first_stable = min(i for i, t in enumerate(trends) if t == "stable")
        assert last_increasing < first_stable

    def test_recommendations_larger_budget_fills_full_gaps(self, client):
        """Test a large budget fills every gap fully."""
        data = client.get("/api/restocking/recommendations?budget=100000").json()
        for item in data["items"]:
            assert item["quantity"] == item["demand_gap"]

    def test_recommendations_negative_budget(self, client):
        """Test negative budget is rejected."""
        response = client.get("/api/restocking/recommendations?budget=-5")
        assert response.status_code == 400
        assert "detail" in response.json()

    def test_recommendations_missing_budget(self, client):
        """Test missing budget is a validation error."""
        response = client.get("/api/restocking/recommendations")
        assert response.status_code == 422


class TestRestockingOrders:
    """Test suite for submitted restocking orders."""

    def test_no_orders_initially(self, client):
        """Test the submitted orders list starts empty."""
        response = client.get("/api/restocking/orders")
        assert response.status_code == 200
        assert response.json() == []

    def test_create_order(self, client):
        """Test submitting an order."""
        response = client.post("/api/restocking/orders", json=_order_payload(client, 5000))
        assert response.status_code == 201

        order = response.json()
        assert order["status"] == "Submitted"
        assert order["order_number"].startswith("RST-")
        assert "submitted_date" in order
        assert "expected_delivery_date" in order
        assert len(order["items"]) > 0

    def test_order_lead_time_is_slowest_item(self, client):
        """Test order lead time equals the max item lead time."""
        order = client.post("/api/restocking/orders", json=_order_payload(client, 5000)).json()
        assert order["lead_time_days"] == max(i["lead_time_days"] for i in order["items"])

    def test_order_total_calculation(self, client):
        """Test order total is the sum of its lines."""
        order = client.post("/api/restocking/orders", json=_order_payload(client, 5000)).json()
        assert abs(order["total_cost"] - sum(i["line_total"] for i in order["items"])) < 0.01
        assert order["total_cost"] <= order["budget"]

    def test_created_order_appears_in_list(self, client):
        """Test a submitted order is returned by the list endpoint, newest first."""
        first = client.post("/api/restocking/orders", json=_order_payload(client, 5000)).json()
        second = client.post("/api/restocking/orders", json=_order_payload(client, 1000)).json()

        orders = client.get("/api/restocking/orders").json()
        assert [o["id"] for o in orders] == [second["id"], first["id"]]

    def test_create_order_empty_items(self, client):
        """Test an order with no items is rejected."""
        response = client.post("/api/restocking/orders", json={"budget": 1000, "items": []})
        assert response.status_code == 400

    def test_create_order_unknown_sku(self, client):
        """Test an unknown SKU is rejected."""
        response = client.post(
            "/api/restocking/orders",
            json={"budget": 1000, "items": [{"item_sku": "NOPE-999", "quantity": 1}]},
        )
        assert response.status_code == 400
        assert "unknown sku" in response.json()["detail"].lower()

    def test_create_order_invalid_quantity(self, client):
        """Test non-positive quantities are rejected."""
        response = client.post(
            "/api/restocking/orders",
            json={"budget": 1000, "items": [{"item_sku": "WDG-001", "quantity": 0}]},
        )
        assert response.status_code == 400

    def test_create_order_over_budget(self, client):
        """Test an order exceeding the budget is rejected."""
        response = client.post(
            "/api/restocking/orders",
            json={"budget": 10, "items": [{"item_sku": "WDG-001", "quantity": 100}]},
        )
        assert response.status_code == 400
        assert "budget" in response.json()["detail"].lower()

    def test_create_order_missing_fields(self, client):
        """Test a malformed body is a validation error."""
        response = client.post("/api/restocking/orders", json={})
        assert response.status_code == 422


class TestDemandForecastFields:
    """Test the new demand forecast fields used for restocking."""

    def test_demand_has_cost_and_lead_time(self, client):
        """Test forecasts include unit_cost and lead_time_days."""
        data = client.get("/api/demand").json()
        assert len(data) > 0
        for item in data:
            assert item["unit_cost"] > 0
            assert isinstance(item["lead_time_days"], int)
            assert item["lead_time_days"] > 0
