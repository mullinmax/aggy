import json


def test_service_worker_served_at_root(client):
    """The service worker must be reachable at the site root so its scope can
    cover the whole app (a worker under /static could only control /static)."""
    response = client.get("/sw.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert response.headers.get("service-worker-allowed") == "/"
    assert response.headers.get("cache-control") == "no-cache"


def test_manifest_served(client):
    response = client.get("/manifest.webmanifest")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/manifest+json")

    manifest = json.loads(response.content)
    assert manifest["start_url"] == "/app"
    assert manifest["display"] == "standalone"
    # At least one 512px icon is required for installability.
    assert any(icon["sizes"] == "512x512" for icon in manifest["icons"])


def test_app_page_links_pwa_assets(client):
    html = client.get("/app").text
    assert 'rel="manifest"' in html
    assert "js/pwa.js" in html
    assert "apple-touch-icon" in html
    assert 'name="theme-color"' in html


def test_login_page_links_pwa_assets(client):
    html = client.get("/login").text
    assert 'rel="manifest"' in html
    assert "js/pwa.js" in html
