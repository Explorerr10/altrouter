import pytest
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect

from app.main import create_app


@pytest.fixture()
def client(tmp_path):
    app = create_app(config_dir=tmp_path)
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def test_login_default_admin(client):
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "admin"
    assert data["default_password"] is True


def test_login_wrong_password(client):
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "nope"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "invalid_credentials"


def test_me_requires_auth(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_with_session(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.json()["username"] == "admin"


def test_logout(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_change_password(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    resp = client.post(
        "/api/auth/password",
        json={"old_password": "admin", "new_password": "newsecret"},
    )
    assert resp.status_code == 200
    client.post("/api/auth/logout")
    bad = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert bad.status_code == 401
    good = client.post("/api/auth/login", json={"username": "admin", "password": "newsecret"})
    assert good.status_code == 200
    assert good.json()["default_password"] is False


def test_change_password_wrong_old(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    resp = client.post(
        "/api/auth/password", json={"old_password": "bad", "new_password": "newsecret"}
    )
    assert resp.status_code == 400


def test_short_new_password_rejected(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    resp = client.post(
        "/api/auth/password", json={"old_password": "admin", "new_password": "123"}
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "validation_error"


def test_protected_endpoint_requires_auth(client):
    assert client.get("/api/system/info").status_code == 401


def test_ws_unauthorized(client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/api/ws/stats") as ws:
            ws.receive_json()
    assert exc.value.code == 4401


def test_ws_authorized(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    cookies = dict(client.cookies)
    with client.websocket_connect("/api/ws/stats", cookies=cookies) as ws:
        sample = ws.receive_json()
    assert "cpu_percent" in sample
    assert "ram_percent" in sample
    assert "interfaces" in sample
