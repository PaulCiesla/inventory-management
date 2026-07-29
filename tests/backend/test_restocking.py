"""
Tests for the restocking API endpoints: enriched demand forecasts and
restocking order submission.
"""
from datetime import date, timedelta

import pytest

import mock_data


@pytest.fixture(autouse=True)
def reset_order_lists():
    """Restore both order lists per test.

    Submitting a restock order mutates module-level state, so without this the submitted
    orders leak across the whole session and into other test files' assertions.
    """
    original_orders = list(mock_data.orders)
    original_restocking = list(mock_data.restocking_orders)
    yield
    mock_data.orders[:] = original_orders
    mock_data.restocking_orders[:] = original_restocking


class TestEnrichedDemandEndpoint:
    """Test suite for GET /api/demand/enriched."""

    def test_get_enriched_demand(self, client):
        """Enriched demand returns all forecasts with resolved cost fields."""
        response = client.get("/api/demand/enriched")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        # 9 seed forecast items
        assert len(data) == 9

        for item in data:
            # Original demand fields carried through
            assert "item_sku" in item
            assert "item_name" in item
            assert "trend" in item
            # Restocking enrichment fields
            assert "unit_cost" in item
            assert "cost_source" in item
            assert "lead_time_days" in item

    def test_enriched_unit_cost_positive(self, client):
        """Every enriched item gets a usable positive price."""
        data = client.get("/api/demand/enriched").json()
        for item in data:
            assert isinstance(item["unit_cost"], (int, float))
            assert item["unit_cost"] > 0

    def test_enriched_cost_source_valid(self, client):
        """cost_source is one of the three known resolution strategies."""
        data = client.get("/api/demand/enriched").json()
        valid = {"sku", "name", "synthesized"}
        for item in data:
            assert item["cost_source"] in valid

    def test_enriched_lead_time_in_range(self, client):
        """Lead time is a deterministic 7-21 day window."""
        data = client.get("/api/demand/enriched").json()
        for item in data:
            assert isinstance(item["lead_time_days"], int)
            assert 7 <= item["lead_time_days"] <= 21

    def test_sku_match_uses_inventory_cost(self, client):
        """PSU-501 matches inventory by SKU -> real unit_cost, source 'sku'."""
        data = client.get("/api/demand/enriched").json()
        psu = next(i for i in data if i["item_sku"] == "PSU-501")
        assert psu["cost_source"] == "sku"
        assert abs(psu["unit_cost"] - 18.99) < 0.01

    def test_name_match_uses_inventory_cost(self, client):
        """SNR-420 has no SKU match but matches inventory by name -> source 'name'."""
        data = client.get("/api/demand/enriched").json()
        snr = next(i for i in data if i["item_sku"] == "SNR-420")
        assert snr["cost_source"] == "name"
        assert abs(snr["unit_cost"] - 89.5) < 0.01

    def test_unmatched_item_synthesized(self, client):
        """WDG-001 has no inventory match -> price is synthesized."""
        data = client.get("/api/demand/enriched").json()
        wdg = next(i for i in data if i["item_sku"] == "WDG-001")
        assert wdg["cost_source"] == "synthesized"

    def test_synthesized_cost_is_deterministic(self, client):
        """Synthesized prices must be identical across calls (stable across reloads)."""
        first = client.get("/api/demand/enriched").json()
        second = client.get("/api/demand/enriched").json()
        first_by_sku = {i["item_sku"]: i["unit_cost"] for i in first}
        second_by_sku = {i["item_sku"]: i["unit_cost"] for i in second}
        assert first_by_sku == second_by_sku


class TestRestockingOrderSubmission:
    """Test suite for POST /api/restocking/orders."""

    def _sample_payload(self):
        return {
            "items": [
                {"sku": "WDG-001", "name": "Industrial Widget Type A",
                 "quantity": 150, "unit_price": 20.0, "lead_time_days": 10},
                {"sku": "GSK-203", "name": "High-Temperature Gasket",
                 "quantity": 100, "unit_price": 5.5, "lead_time_days": 18},
            ],
            "budget": 10000,
        }

    def test_create_restocking_order(self, client):
        """Submitting a restock order returns a created Submitted order."""
        response = client.post("/api/restocking/orders", json=self._sample_payload())
        assert response.status_code == 201

        order = response.json()
        assert order["status"] == "Submitted"
        assert order["order_number"].startswith("ORD-")
        assert order["customer"] == "Internal Restock"
        assert len(order["items"]) == 2

    def test_total_value_calculation(self, client):
        """total_value equals the sum of quantity * unit_price across items."""
        payload = self._sample_payload()
        order = client.post("/api/restocking/orders", json=payload).json()
        expected = sum(i["quantity"] * i["unit_price"] for i in payload["items"])
        assert abs(order["total_value"] - expected) < 0.01

    def test_expected_delivery_uses_max_lead_time(self, client):
        """Expected delivery = order_date + the largest item lead time."""
        payload = self._sample_payload()
        order = client.post("/api/restocking/orders", json=payload).json()

        order_date = date.fromisoformat(order["order_date"])
        expected_delivery = date.fromisoformat(order["expected_delivery"])
        max_lead = max(i["lead_time_days"] for i in payload["items"])
        assert expected_delivery == order_date + timedelta(days=max_lead)

    def test_submitted_order_appears_in_restocking_list(self, client):
        """A submitted order is retrievable via GET /api/restocking/orders."""
        created = client.post("/api/restocking/orders", json=self._sample_payload()).json()

        listed = client.get("/api/restocking/orders").json()
        order_numbers = [o["order_number"] for o in listed]
        assert created["order_number"] in order_numbers
        # All returned orders carry the Submitted status
        for o in listed:
            assert o["status"] == "Submitted"

    def test_submitted_order_stays_out_of_orders_list(self, client):
        """Restock orders must not surface in /api/orders, which backs the revenue math."""
        created = client.post("/api/restocking/orders", json=self._sample_payload()).json()

        listed = client.get("/api/orders").json()
        assert created["order_number"] not in [o["order_number"] for o in listed]

    def test_restock_order_ids_do_not_collide_with_orders(self, client):
        """Ids are allocated across both lists so a restock never reuses a customer order id."""
        existing_ids = {o["id"] for o in client.get("/api/orders").json()}

        first = client.post("/api/restocking/orders", json=self._sample_payload()).json()
        second = client.post("/api/restocking/orders", json=self._sample_payload()).json()

        assert first["id"] not in existing_ids
        assert second["id"] not in existing_ids
        assert first["id"] != second["id"]

    def test_orders_list_still_valid_after_submission(self, client):
        """Appended order must not break the List[Order]-validated /api/orders."""
        client.post("/api/restocking/orders", json=self._sample_payload())
        response = client.get("/api/orders")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_empty_items_rejected(self, client):
        """An order with no items is a bad request."""
        response = client.post("/api/restocking/orders", json={"items": [], "budget": 100})
        assert response.status_code == 400
        assert "detail" in response.json()

    def test_category_filter_survives_submitted_order(self, client):
        """Filtering by category must not break once a restock order exists.

        Regression: submitted orders store category as an explicit None, and apply_filters
        used item.get('category', '').lower(). The '' default never fires for a key that is
        present with value None, so a single restock order made every category-filtered
        request raise AttributeError -> HTTP 500 for the life of the process.
        """
        client.post("/api/restocking/orders", json=self._sample_payload())

        response = client.get("/api/orders?category=Sensors")
        assert response.status_code == 200
        # The category-less restock order must simply be excluded, not blow up the request
        for order in response.json():
            assert (order.get("category") or "").lower() == "sensors"

    def test_dashboard_category_filter_survives_submitted_order(self, client):
        """The dashboard shares apply_filters, so it must survive the same case."""
        client.post("/api/restocking/orders", json=self._sample_payload())

        response = client.get("/api/dashboard/summary?category=Sensors")
        assert response.status_code == 200
        assert "total_orders_value" in response.json()

    def test_warehouse_filter_survives_submitted_order(self, client):
        """Same for warehouse, which submitted orders also store as None."""
        client.post("/api/restocking/orders", json=self._sample_payload())

        response = client.get("/api/orders?warehouse=Tokyo")
        assert response.status_code == 200
        for order in response.json():
            assert order["warehouse"] == "Tokyo"


class TestRestockingRevenueIsolation:
    """Restock spend must never be aggregated as revenue.

    Regression: restock orders were appended to the same `orders` list that backs every
    revenue figure, so buying parts inflated reported earnings.
    """

    def _payload(self):
        return {
            "items": [
                {"sku": "WDG-001", "name": "Industrial Widget Type A",
                 "quantity": 100, "unit_price": 250.0, "lead_time_days": 10},
            ],
            "budget": 100000,
        }

    def test_dashboard_revenue_unchanged(self, client):
        """total_orders_value backs the Revenue YTD/MTD tile and its goal bar."""
        before = client.get("/api/dashboard/summary").json()["total_orders_value"]

        created = client.post("/api/restocking/orders", json=self._payload()).json()
        assert created["total_value"] == 25000.0

        after = client.get("/api/dashboard/summary").json()["total_orders_value"]
        assert after == before

    def test_monthly_trends_bucket_count_unchanged(self, client):
        """A new month bucket would skew Reports' avgMonthlyRevenue (total / bucket count)."""
        before = client.get("/api/reports/monthly-trends").json()
        client.post("/api/restocking/orders", json=self._payload())
        after = client.get("/api/reports/monthly-trends").json()

        assert len(after) == len(before)
        assert [m["revenue"] for m in after] == [m["revenue"] for m in before]

    def test_quarterly_report_unchanged(self, client):
        """Quarterly hardcodes 2025, so contamination here desyncs it from monthly-trends."""
        before = client.get("/api/reports/quarterly").json()
        client.post("/api/restocking/orders", json=self._payload())
        after = client.get("/api/reports/quarterly").json()

        assert after == before

    def test_orders_endpoint_revenue_unchanged(self, client):
        """Dashboard.vue rolls up product revenue client-side from /api/orders."""
        def orders_total():
            return sum(o["total_value"] for o in client.get("/api/orders").json())

        before = orders_total()
        client.post("/api/restocking/orders", json=self._payload())
        assert orders_total() == before
