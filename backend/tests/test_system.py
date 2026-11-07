import pytest
from fastapi.testclient import TestClient

import app.system.service as service
from app.main import create_app
from app.network.manager import InterfaceManager
from app.system.service import AccessStore


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ALTROUTER_TLS_DIR", str(tmp_path / "certs"))
    calls = []

    def applier():
        calls.append(1)

    manager = InterfaceManager(
        tmp_path, applier=applier, mgmt_iface="enp9s0f0", confirm_timeout=3600
    )
    app = create_app(config_dir=tmp_path, network_manager=manager)
    client = TestClient(app, base_url="https://testserver")
    client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    return client, tmp_path


def login(client, username, password):
    client.post("/api/auth/login", json={"username": username, "password": password})


def test_users_and_roles(env):
    client, _ = env
    assert client.get("/api/system/users").json() == [{"username": "admin", "role": "admin"}]
    resp = client.post(
        "/api/system/users", json={"username": "watch", "password": "secret1", "role": "viewer"}
    )
    assert resp.status_code == 201
    assert client.post(
        "/api/system/users", json={"username": "watch", "password": "secret1", "role": "viewer"}
    ).status_code == 400

    viewer = TestClient(client.app, base_url="https://testserver")
    login(viewer, "watch", "secret1")
    assert viewer.get("/api/system/users").status_code == 403
    assert viewer.get("/api/network/interfaces/config").status_code == 200
    assert viewer.put("/api/network/routes", json={"routes": []}).status_code == 403
    assert viewer.post("/api/network/interfaces/confirm").status_code == 403
    assert viewer.get("/api/system/journal").status_code == 200

    assert client.put("/api/system/users/admin", json={"role": "viewer"}).status_code == 400
    assert client.delete("/api/system/users/admin").status_code == 400
    assert client.put("/api/system/users/watch", json={"password": "secret2"}).status_code == 200
    assert viewer.get("/api/auth/me").status_code == 401
    login(viewer, "watch", "secret2")
    assert viewer.get("/api/auth/me").status_code == 200
    assert client.delete("/api/system/users/watch").status_code == 200
    assert viewer.get("/api/auth/me").status_code == 401


def test_journal_records_changes(env):
    client, _ = env
    client.put("/api/network/routes", json={"routes": []})
    client.post("/api/network/interfaces/confirm")
    entries = client.get("/api/system/journal").json()
    actions = [e["action"] for e in entries]
    assert "applied" in actions
    assert "committed" in actions
    assert entries[-1]["username"] == "admin"


def test_backup_roundtrip(env):
    client, cfg = env
    data = client.get("/api/system/backup").content
    assert data[:2] == b"\x1f\x8b"
    assert client.put("/api/system/backup", content=data).status_code == 200
    assert (cfg / "config.json").exists()
    assert client.put("/api/system/backup", content=b"garbage").status_code == 400


def test_backup_requires_admin(env):
    client, _ = env
    client.post(
        "/api/system/users", json={"username": "watch", "password": "secret1", "role": "viewer"}
    )
    login(client, "watch", "secret1")
    assert client.get("/api/system/backup").status_code == 403
    assert client.put("/api/system/backup", content=b"x").status_code == 403


def test_diag_input_validation(env):
    client, _ = env
    assert client.post("/api/system/diag/ping", json={"host": "bad host"}).status_code == 400
    assert client.post("/api/system/diag/tcpdump", json={"iface": "eth0; x"}).status_code == 400
    assert (
        client.post("/api/system/diag/tcpdump", json={"iface": "eth0", "filter": "--bad"})
        .status_code
        == 400
    )
    assert client.get("/api/system/logs", params={"unit": "hack"}).status_code == 400
    too_many = client.post("/api/system/diag/ping", json={"host": "1.1.1.1", "count": 99})
    assert too_many.status_code == 422


def test_ssh_toggle(env, monkeypatch):
    client, _ = env
    monkeypatch.setattr(service, "ssh_status", lambda: {"active": True, "enabled": True})
    monkeypatch.setattr(service, "ssh_set", lambda enabled: None)
    assert client.get("/api/system/ssh").json() == {"active": True, "enabled": True}
    assert client.put("/api/system/ssh", json={"enabled": True}).status_code == 200
    assert client.get("/api/system/journal").json()[-1]["action"] == "ssh_enabled"


def test_ssh_config(env, monkeypatch):
    client, _ = env
    monkeypatch.setattr(service, "ssh_apply", lambda port, cidr, password_auth=True: None)
    assert client.put("/api/system/ssh/config", json={"port": 9000}).status_code == 422
    assert (
        client.put("/api/system/ssh/config", json={"port": 2222, "allow_subnet": "10.0.0.0/33"})
        .status_code
        == 422
    )
    assert (
        client.put("/api/system/ssh/config", json={"port": 2222, "allow_subnet": "10.0.0.5/24"})
        .status_code
        == 422
    )
    assert client.put("/api/system/ssh/config", json={"port": 2222}).status_code == 200
    assert (
        client.put(
            "/api/system/ssh/config", json={"port": 2222, "password_auth": False}
        ).status_code
        == 200
    )
    assert client.get("/api/system/journal").json()[-1]["action"] == "ssh_config"


def test_ssh_keys(env, monkeypatch):
    client, _ = env
    monkeypatch.setattr(service, "ssh_users", lambda: [{"username": "root", "uid": 0}])
    monkeypatch.setattr(
        service,
        "ssh_keys_list",
        lambda user: [{"index": 1, "fingerprint": "FP", "comment": "c"}],
    )
    monkeypatch.setattr(service, "ssh_key_add", lambda user, key: "FP")
    monkeypatch.setattr(service, "ssh_key_del", lambda user, index: None)
    assert client.get("/api/system/ssh/keys", params={"user": "root"}).json() == [
        {"index": 1, "fingerprint": "FP", "comment": "c"}
    ]
    assert client.put(
        "/api/system/ssh/keys", json={"user": "root", "key": "ssh-ed25519 AAAA test"}
    ).json() == {"ok": True, "fingerprint": "FP"}
    assert client.delete("/api/system/ssh/keys/root/1").status_code == 200
    assert client.get("/api/system/ssh/keys", params={"user": "nobody"}).status_code == 404
    assert (
        client.put("/api/system/ssh/keys", json={"user": "nobody", "key": "x" * 30}).status_code
        == 404
    )


def test_updates(env, monkeypatch):
    client, _ = env
    monkeypatch.setattr(service, "updates_count", lambda: 3)
    monkeypatch.setattr(service, "updates_apply", lambda: "upgraded")
    assert client.get("/api/system/updates").json() == {"count": 3}
    assert client.post("/api/system/updates/apply").json() == {"ok": True, "output": "upgraded"}


def test_power(env, monkeypatch):
    client, _ = env
    assert client.post("/api/system/power", json={"action": "format"}).status_code == 422
    monkeypatch.setattr(service, "power", lambda action: None)
    assert client.post("/api/system/power", json={"action": "reboot"}).status_code == 200
    assert client.get("/api/system/journal").json()[-1]["action"] == "reboot"


def test_tls(env):
    client, _ = env
    assert "error" in client.get("/api/system/tls").json()
    assert client.put("/api/system/tls", json={"cert": "x", "key": "y"}).status_code == 400


def test_management_only_access(env):
    client, cfg = env
    assert client.put("/api/system/access", json={"management_only": True}).status_code == 200
    assert client.get("/api/health").status_code == 403
    AccessStore(cfg).save({"management_only": False})
    assert client.get("/api/health").status_code == 200
