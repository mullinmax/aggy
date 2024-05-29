def test_docs_reroute(client):
    """Tests the root reroute."""
    response = client.get("/")
    assert response.status_code == 200
    assert response.url == "http://testserver/docs"
