def test_docs_reroute(client):
    """Tests the root reroute."""
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/app"


def test_get_version(client):
    """Tests the get version route."""
    response = client.get("/version")
    assert response.status_code == 200
    assert response.json() == {"version": "0.0.0-beta"}


def test_health(client):
    """Tests the health check route."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"message": "success"}
