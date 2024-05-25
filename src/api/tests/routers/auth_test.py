import jwt
from config import config


def test_create_user(client, unique_user):
    response = client.post(
        "/auth/signup", json={"username": unique_user.name, "password": "password"}
    )
    assert response.status_code == 200
    assert response.json() == {"message": "success"}


def test_create_user_duplicate(client, unique_user):
    response = client.post(
        "/auth/signup", json={"username": unique_user.name, "password": "password"}
    )
    assert response.status_code == 200
    assert response.json() == {"message": "success"}

    response = client.post(
        "/auth/signup", json={"username": unique_user.name, "password": "password"}
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "Username already registered"}


def test_create_user_no_username(client, unique_user):
    response = client.post("/auth/signup", json={"password": "password"})
    assert response.status_code == 422


def test_create_user_no_password(client, unique_user):
    response = client.post("/auth/signup", json={"username": unique_user.name})
    assert response.status_code == 422


def test_create_user_no_data(client, unique_user):
    response = client.post("/auth/signup", json={})
    assert response.status_code == 422


def test_get_token(client, unique_user):
    response = client.post(
        "/auth/signup", json={"username": unique_user.name, "password": "password"}
    )
    assert response.status_code == 200

    response = client.post(
        "/auth/login", json={"username": unique_user.name, "password": "password"}
    )
    assert "token" in response.json()
    assert len(response.json()["token"]) > 0
    assert "token_type" in response.json()

    headers = {"Authorization": f"Bearer {response.json()['token']}"}

    response = client.get("/auth/token_check", headers=headers)
    assert response.status_code == 200


def test_get_token_bad_user(client, unique_user):
    response = client.post(
        "/auth/signup", json={"username": unique_user.name, "password": "password"}
    )
    assert response.status_code == 200

    response = client.post(
        "/auth/login", json={"username": "bad_user", "password": "password"}
    )
    assert response.status_code == 404


def test_get_token_bad_password(client, unique_user):
    response = client.post(
        "/auth/signup", json={"username": unique_user.name, "password": "password"}
    )
    assert response.status_code == 200

    response = client.post(
        "/auth/login", json={"username": unique_user.name, "password": "bad_password"}
    )
    assert response.status_code == 401


def test_get_token_no_user(client, unique_user):
    response = client.post(
        "/auth/signup", json={"username": unique_user.name, "password": "password"}
    )
    assert response.status_code == 200

    response = client.post("/auth/login", json={"password": "password"})
    assert response.status_code == 422


def test_get_token_no_password(client, unique_user):
    response = client.post(
        "/auth/signup", json={"username": unique_user.name, "password": "password"}
    )
    assert response.status_code == 200

    response = client.post("/auth/login", json={"username": unique_user.name})
    assert response.status_code == 422


def test_get_token_no_data(client, unique_user):
    response = client.post(
        "/auth/signup", json={"username": unique_user.name, "password": "password"}
    )
    assert response.status_code == 200

    response = client.post("/auth/login", json={})
    assert response.status_code == 422


def test_get_token_expired(client, unique_user):
    response = client.post(
        "/auth/signup", json={"username": unique_user.name, "password": "password"}
    )
    assert response.status_code == 200

    # create an expired token
    exp_token = jwt.encode(
        {"user": unique_user.name, "exp": 0},
        config.get("JWT_SECRET"),
        algorithm=config.get("JWT_ALGORITHM"),
    )

    headers = {"Authorization": f"Bearer {exp_token}"}

    response = client.get("/auth/token_check", headers=headers)
    assert response.status_code == 401
