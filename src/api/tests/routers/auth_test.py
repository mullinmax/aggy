def test_create_user(client, unique_user):
    response = client.post(
        "/auth/signup", data={"username": unique_user.name, "password": "password"}
    )
    assert response.status_code == 200
    assert response.json() == {"acknowledged": True}

    unique_user.delete()
