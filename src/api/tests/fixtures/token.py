import pytest
from fastapi.testclient import TestClient

from db.user import User


@pytest.fixture(scope="function")
def token(client: TestClient, existing_user: User) -> str:
    response = client.post(
        "/auth/login",
        json={"username": existing_user.name, "password": "password"},
    )

    return response.json()["token"]
