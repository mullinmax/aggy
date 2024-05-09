def test_create_user(client, unique_user):
    response = client.post(
        "/auth/signup", json={"username": unique_user.name, "password": "password"}
    )
    print(response.json())
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


# def test_get_token(client, unique_user):
#     response = client.post(
#         "/auth/signup", json={"username": unique_user.name, "password": "password"}
#     )
#     assert response.status_code == 200

#     response = client.post(
#         "/auth/login", json={"username": unique_user.name, "password": "password"}
#     )
#     assert "access_token" in response.json()
#     assert len(response.json()["access_token"]) > 0
#     assert "token_type" in response.json()

#     headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

#     response = client.get(
#         "/auth/token_check", headers=headers
#     )
#     assert response.status_code == 200

# def test_get_token_bad_user(client, unique_user):
#     response = client.post(
#         "/auth/signup", json={"username": unique_user.name, "password": "password"}
#     )
#     assert response.status_code == 200

#     response = client.post(
#         "/auth/login", json={"username": "bad_user", "password": "password"}
#     )
#     assert response.status_code == 404

# def test_get_token_bad_password(client, unique_user):
#     response = client.post(
#         "/auth/signup", json={"username": unique_user.name, "password": "password"}
#     )
#     assert response.status_code == 200

#     response = client.post(
#         "/auth/login", json={"username": unique_user.name, "password": "bad_password"}
#     )
#     assert response.status_code == 401

# def test_get_token_no_user(client, unique_user):
#     response = client.post(
#         "/auth/signup", json={"username": unique_user.name, "password": "password"}
#     )
#     assert response.status_code == 200

#     response = client.post(
#         "/auth/login", json={"password": "password"}
#     )
#     assert response.status_code == 422

# def test_get_token_no_password(client, unique_user):
#     response = client.post(
#         "/auth/signup", json={"username": unique_user.name, "password": "password"}
#     )
#     assert response.status_code == 200

#     response = client.post(
#         "/auth/login", json={"username": unique_user.name}
#     )
#     assert response.status_code == 422

# def test_get_token_no_data(client, unique_user):
#     response = client.post(
#         "/auth/signup", json={"username": unique_user.name, "password": "password"}
#     )
#     assert response.status_code == 200

#     response = client.post(
#         "/auth/login", json={}
#     )
#     assert response.status_code == 422

# def test_get_token_expired(client, unique_user):
#     response = client.post(
#         "/auth/signup", json={"username": unique_user.name, "password": "password"}
#     )
#     assert response.status_code == 200

#     response = client.post(
#         "/auth/login", json={"username": unique_user.name, "password": "password", "days_to_live": -10}
#     )
#     # you're dumb for requesting a token that's already expired, but it's allowed
#     assert response.status_code == 200

#     headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

#     response = client.get(
#         "/auth/token_check", headers=headers
#     )
#     assert response.status_code == 401
