"""
Tests for the purchase order API endpoints raised from dashboard backlog rows.
"""
import pytest

import mock_data


@pytest.fixture(autouse=True)
def reset_purchase_orders():
    """Purchase orders live in a module-level list, so restore it per test.

    /api/backlog derives has_purchase_order from this list, so a leaked PO would
    change the backlog responses asserted by the dashboard tests.
    """
    original = list(mock_data.purchase_orders)
    yield
    mock_data.purchase_orders[:] = original


@pytest.fixture
def backlog_item_id(client):
    """Id of the first backlog item, used as the PO target."""
    backlog = client.get("/api/backlog").json()
    assert len(backlog) > 0
    return backlog[0]["id"]


@pytest.fixture
def backlog_ids(client):
    """All backlog item ids, for tests needing more than one PO target."""
    backlog = client.get("/api/backlog").json()
    assert len(backlog) >= 2
    return [item["id"] for item in backlog]


def po_payload(backlog_item_id, **overrides):
    """Valid payload for POST /api/purchase-orders."""
    payload = {
        "backlog_item_id": backlog_item_id,
        "supplier_name": "Nakamura Motors KK",
        "quantity": 350,
        "unit_cost": 12.5,
        "expected_delivery_date": "2026-08-12",
        "notes": "expedite"
    }
    payload.update(overrides)
    return payload


class TestPurchaseOrderEndpoints:
    """Test suite for the /api/purchase-orders endpoints."""

    def test_create_purchase_order(self, client, backlog_item_id):
        """Test creating a purchase order for a backlog item."""
        response = client.post("/api/purchase-orders", json=po_payload(backlog_item_id))
        assert response.status_code == 201

        po = response.json()
        assert po["id"].startswith("PO-")
        assert po["backlog_item_id"] == backlog_item_id
        assert po["supplier_name"] == "Nakamura Motors KK"
        assert po["quantity"] == 350
        assert po["unit_cost"] == 12.5
        assert po["expected_delivery_date"] == "2026-08-12"
        assert po["status"] == "pending"
        assert po["notes"] == "expedite"

    def test_create_purchase_order_without_notes(self, client, backlog_item_id):
        """Test that notes are optional."""
        payload = po_payload(backlog_item_id)
        del payload["notes"]

        response = client.post("/api/purchase-orders", json=payload)
        assert response.status_code == 201
        assert response.json()["notes"] is None

    def test_get_purchase_order_by_backlog_item(self, client, backlog_item_id):
        """Test getting a purchase order by its backlog item id."""
        created = client.post("/api/purchase-orders", json=po_payload(backlog_item_id)).json()

        response = client.get(f"/api/purchase-orders/{backlog_item_id}")
        assert response.status_code == 200

        po = response.json()
        assert po["id"] == created["id"]
        assert po["backlog_item_id"] == backlog_item_id

    def test_get_purchase_order_for_item_without_one(self, client, backlog_item_id):
        """Test that a backlog item with no purchase order returns 404."""
        response = client.get(f"/api/purchase-orders/{backlog_item_id}")
        assert response.status_code == 404

        data = response.json()
        assert "detail" in data
        assert "no purchase order found" in data["detail"].lower()

    def test_create_purchase_order_nonexistent_backlog_item(self, client):
        """Test creating a purchase order against an unknown backlog item."""
        response = client.post("/api/purchase-orders", json=po_payload("nonexistent-999"))
        assert response.status_code == 404

        data = response.json()
        assert "detail" in data
        assert "not found" in data["detail"].lower()

    def test_create_duplicate_purchase_order(self, client, backlog_item_id):
        """Test that a backlog item can only carry one purchase order."""
        client.post("/api/purchase-orders", json=po_payload(backlog_item_id))

        response = client.post("/api/purchase-orders", json=po_payload(backlog_item_id))
        assert response.status_code == 400
        assert "already has a purchase order" in response.json()["detail"].lower()

    def test_create_purchase_order_zero_quantity(self, client, backlog_item_id):
        """Test that a non-positive quantity is rejected."""
        response = client.post(
            "/api/purchase-orders", json=po_payload(backlog_item_id, quantity=0)
        )
        assert response.status_code == 400
        assert "quantity" in response.json()["detail"].lower()

    def test_create_purchase_order_negative_unit_cost(self, client, backlog_item_id):
        """Test that a negative unit cost is rejected."""
        response = client.post(
            "/api/purchase-orders", json=po_payload(backlog_item_id, unit_cost=-1)
        )
        assert response.status_code == 400
        assert "unit cost" in response.json()["detail"].lower()

    def test_create_purchase_order_missing_supplier(self, client, backlog_item_id):
        """Test that a missing supplier fails Pydantic validation."""
        payload = po_payload(backlog_item_id)
        del payload["supplier_name"]

        response = client.post("/api/purchase-orders", json=payload)
        assert response.status_code == 422

    def test_purchase_order_ids_are_unique(self, client, backlog_ids):
        """Test that separate backlog items get distinct purchase order ids."""
        first, second = backlog_ids[0], backlog_ids[1]

        po_one = client.post("/api/purchase-orders", json=po_payload(first)).json()
        po_two = client.post("/api/purchase-orders", json=po_payload(second)).json()

        assert po_one["id"] != po_two["id"]

    def test_purchase_order_field_types(self, client, backlog_item_id):
        """Test that purchase order fields have the expected types."""
        po = client.post("/api/purchase-orders", json=po_payload(backlog_item_id)).json()

        assert isinstance(po["id"], str)
        assert isinstance(po["quantity"], int)
        assert isinstance(po["unit_cost"], (int, float))
        assert isinstance(po["created_date"], str)
        assert po["quantity"] > 0
        assert po["unit_cost"] >= 0


class TestBacklogPurchaseOrderStatus:
    """Test suite for the purchase order fields exposed on /api/backlog."""

    def test_backlog_starts_without_purchase_orders(self, client):
        """Test that seed backlog items carry no purchase order."""
        for item in client.get("/api/backlog").json():
            assert item["has_purchase_order"] is False
            assert item["purchase_order_id"] is None

    def test_backlog_reflects_created_purchase_order(self, client, backlog_item_id):
        """Test that the backlog exposes the new PO id so the row can show View PO."""
        created = client.post("/api/purchase-orders", json=po_payload(backlog_item_id)).json()

        backlog = client.get("/api/backlog").json()
        target = next(item for item in backlog if item["id"] == backlog_item_id)
        assert target["has_purchase_order"] is True
        assert target["purchase_order_id"] == created["id"]

    def test_other_backlog_items_unaffected(self, client, backlog_item_id):
        """Test that creating one purchase order leaves the other rows alone."""
        client.post("/api/purchase-orders", json=po_payload(backlog_item_id))

        backlog = client.get("/api/backlog").json()
        for item in backlog:
            if item["id"] == backlog_item_id:
                continue
            assert item["has_purchase_order"] is False
            assert item["purchase_order_id"] is None
