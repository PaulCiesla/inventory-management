"""
Tests for the tasks API endpoints backing the TasksModal in the app header.
"""
import pytest

import mock_data


@pytest.fixture(autouse=True)
def reset_tasks():
    """Tasks live in a module-level list, so snapshot and restore it per test.

    Without this, a created task leaks into every later test (and into other
    test files) because the endpoints mutate mock_data.tasks in place.
    """
    original = list(mock_data.tasks)
    yield
    mock_data.tasks[:] = original


@pytest.fixture
def new_task():
    """Valid payload for POST /api/tasks."""
    return {
        "title": "Review Tokyo restock plan",
        "priority": "high",
        "dueDate": "2026-08-05"
    }


class TestTasksEndpoints:
    """Test suite for the /api/tasks endpoints."""

    def test_get_all_tasks(self, client):
        """Test getting all tasks."""
        response = client.get("/api/tasks")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)

    def test_create_task(self, client, new_task):
        """Test creating a task."""
        response = client.post("/api/tasks", json=new_task)
        assert response.status_code == 201

        task = response.json()
        assert task["title"] == new_task["title"]
        assert task["priority"] == new_task["priority"]
        assert task["dueDate"] == new_task["dueDate"]
        assert task["status"] == "pending"
        assert task["id"].startswith("TASK-")

    def test_create_task_defaults_to_medium_priority(self, client):
        """Test that priority defaults to medium when omitted."""
        response = client.post(
            "/api/tasks",
            json={"title": "Chase supplier", "dueDate": "2026-08-05"}
        )
        assert response.status_code == 201
        assert response.json()["priority"] == "medium"

    def test_create_task_trims_title(self, client):
        """Test that surrounding whitespace is stripped from the title."""
        response = client.post(
            "/api/tasks",
            json={"title": "  Padded title  ", "priority": "low", "dueDate": "2026-08-05"}
        )
        assert response.status_code == 201
        assert response.json()["title"] == "Padded title"

    def test_created_task_appears_in_list(self, client, new_task):
        """Test that a created task is returned by the list endpoint."""
        created = client.post("/api/tasks", json=new_task).json()

        data = client.get("/api/tasks").json()
        assert any(task["id"] == created["id"] for task in data)

    def test_tasks_returned_newest_first(self, client):
        """Test that the list returns newest tasks first, as the modal renders them."""
        first = client.post(
            "/api/tasks", json={"title": "Older", "priority": "low", "dueDate": "2026-08-05"}
        ).json()
        second = client.post(
            "/api/tasks", json={"title": "Newer", "priority": "low", "dueDate": "2026-08-06"}
        ).json()

        data = client.get("/api/tasks").json()
        ids = [task["id"] for task in data]
        assert ids.index(second["id"]) < ids.index(first["id"])

    def test_task_ids_are_unique_after_delete(self, client):
        """Test that deleting a task does not cause the next id to collide."""
        first = client.post(
            "/api/tasks", json={"title": "First", "priority": "low", "dueDate": "2026-08-05"}
        ).json()
        second = client.post(
            "/api/tasks", json={"title": "Second", "priority": "low", "dueDate": "2026-08-05"}
        ).json()

        client.delete(f"/api/tasks/{first['id']}")

        third = client.post(
            "/api/tasks", json={"title": "Third", "priority": "low", "dueDate": "2026-08-05"}
        ).json()
        assert third["id"] not in (first["id"], second["id"])

    def test_create_task_empty_title(self, client):
        """Test that a blank title is rejected."""
        response = client.post(
            "/api/tasks",
            json={"title": "   ", "priority": "high", "dueDate": "2026-08-05"}
        )
        assert response.status_code == 400
        assert "detail" in response.json()

    def test_create_task_invalid_priority(self, client):
        """Test that an unsupported priority is rejected."""
        response = client.post(
            "/api/tasks",
            json={"title": "Bad priority", "priority": "urgent", "dueDate": "2026-08-05"}
        )
        assert response.status_code == 400
        assert "detail" in response.json()

    def test_create_task_missing_due_date(self, client):
        """Test that a missing due date fails Pydantic validation."""
        response = client.post("/api/tasks", json={"title": "No date", "priority": "low"})
        assert response.status_code == 422

    def test_toggle_task(self, client, new_task):
        """Test toggling a task between pending and completed."""
        created = client.post("/api/tasks", json=new_task).json()

        response = client.patch(f"/api/tasks/{created['id']}")
        assert response.status_code == 200
        assert response.json()["status"] == "completed"

        response = client.patch(f"/api/tasks/{created['id']}")
        assert response.status_code == 200
        assert response.json()["status"] == "pending"

    def test_toggle_nonexistent_task(self, client):
        """Test toggling a task that doesn't exist."""
        response = client.patch("/api/tasks/TASK-9999")
        assert response.status_code == 404

        data = response.json()
        assert "detail" in data
        assert "not found" in data["detail"].lower()

    def test_delete_task(self, client, new_task):
        """Test deleting a task."""
        created = client.post("/api/tasks", json=new_task).json()

        response = client.delete(f"/api/tasks/{created['id']}")
        assert response.status_code == 200
        assert response.json()["deleted"] == created["id"]

        data = client.get("/api/tasks").json()
        assert all(task["id"] != created["id"] for task in data)

    def test_delete_nonexistent_task(self, client):
        """Test deleting a task that doesn't exist."""
        response = client.delete("/api/tasks/TASK-9999")
        assert response.status_code == 404

        data = response.json()
        assert "detail" in data
        assert "not found" in data["detail"].lower()

    def test_task_field_types(self, client, new_task):
        """Test that task fields have the types the frontend expects."""
        client.post("/api/tasks", json=new_task)

        for task in client.get("/api/tasks").json():
            assert isinstance(task["id"], str)
            assert isinstance(task["title"], str)
            assert task["priority"] in ("high", "medium", "low")
            # camelCase key — TasksModal.vue reads task.dueDate
            assert isinstance(task["dueDate"], str)
            assert task["status"] in ("pending", "completed")
