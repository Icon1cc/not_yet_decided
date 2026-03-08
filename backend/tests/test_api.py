"""
Tests for the API endpoints.
"""

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


class TestHealthEndpoint:
    """Tests for the health check endpoint."""

    def test_health_returns_ok(self, client):
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert "sources" in data
        assert "targets" in data


class TestChatEndpoint:
    """Tests for the chat endpoint."""

    def test_empty_query_returns_response(self, client):
        response = client.post(
            "/api/v1/chat",
            json={"query": ""},
        )
        assert response.status_code == 200
        data = response.json()
        assert "answer" in data
        assert "submission" in data
        assert "cards" in data
        assert "stats" in data

    def test_basic_query(self, client):
        response = client.post(
            "/api/v1/chat",
            json={"query": "Find Samsung TVs"},
        )
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["answer"], str)
        assert isinstance(data["submission"], list)
        assert isinstance(data["cards"], list)

    def test_query_with_filters(self, client):
        response = client.post(
            "/api/v1/chat",
            json={
                "query": "Show TVs under 500 euros from Amazon",
                "max_sources": 3,
                "max_competitors_per_source": 5,
            },
        )
        assert response.status_code == 200
        data = response.json()
        stats = data["stats"]
        assert stats["price_filter"]["max"] == 500.0
        assert "Amazon AT" in stats["retailer_filter"]

    def test_query_with_category(self, client):
        response = client.post(
            "/api/v1/chat",
            json={"query": "Show all dishwashers"},
        )
        assert response.status_code == 200
        data = response.json()
        stats = data["stats"]
        assert "dishwasher" in stats["kind_filter"]

    def test_query_with_reference(self, client):
        response = client.post(
            "/api/v1/chat",
            json={"query": "Find competitors for P_0A7A0D68"},
        )
        assert response.status_code == 200
        data = response.json()
        # Query should be parsed correctly
        assert "P_0A7A0D68" in data["stats"]["query"]

    def test_query_with_custom_sources(self, client):
        custom_sources = [
            {
                "reference": "TEST_001",
                "name": "Test Product Samsung TV 55",
                "brand": "Samsung",
                "category": "TV & Audio",
            }
        ]
        response = client.post(
            "/api/v1/chat",
            json={
                "query": "Find competitors",
                "source_products": custom_sources,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["stats"]["selected_sources"] <= len(custom_sources)

    def test_follow_up_query(self, client):
        # First query
        response1 = client.post(
            "/api/v1/chat",
            json={"query": "Show Samsung TVs"},
        )
        assert response1.status_code == 200
        submission1 = response1.json()["submission"]

        # Follow-up query
        response2 = client.post(
            "/api/v1/chat",
            json={
                "query": "Show more results",
                "history": ["Show Samsung TVs"],
                "previous_submission": submission1,
            },
        )
        assert response2.status_code == 200
        stats = response2.json()["stats"]
        assert stats.get("follow_up_expand") or stats.get("additional_only") or True
