from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_health_has_version():
    resp = client.get("/api/health")
    assert resp.json()["version"]


def test_spa_fallback(tmp_path, monkeypatch):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<html>spa</html>", encoding="utf-8")
    monkeypatch.setenv("ALTROUTER_STATIC_DIR", str(web))
    from app.main import create_app

    spa = TestClient(create_app(config_dir=tmp_path), base_url="https://testserver")
    page = spa.get("/login")
    assert page.status_code == 200 and "spa" in page.text
    unknown = spa.get("/api/nope")
    assert unknown.status_code == 404 and unknown.json()["detail"] == "Not Found"
