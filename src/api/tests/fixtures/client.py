from fastapi.testclient import TestClient
import pytest

from main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
