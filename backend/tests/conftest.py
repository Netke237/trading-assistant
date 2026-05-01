import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.fixture
def client():
    """Synchronous TestClient for simple route tests."""
    from fastapi.testclient import TestClient
    return TestClient(app)
