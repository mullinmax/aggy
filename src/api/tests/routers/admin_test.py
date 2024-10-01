def test_docs_reroute(client):
    """Tests the root reroute."""
    response = client.get("/")
    assert response.status_code == 200
    assert response.url == "http://testserver/docs"


def test_get_version(client):
    """Tests the get version route."""
    response = client.get("/version")
    assert response.status_code == 200
    assert response.json() == {"version": "0.0.0-beta"}
