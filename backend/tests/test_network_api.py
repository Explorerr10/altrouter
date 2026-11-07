import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.network.manager import InterfaceManager


@pytest.fixture()
def env(tmp_path):
    calls = []

    def applier():
        calls.append(1)

    manager = InterfaceManager(
        tmp_path, applier=applier, mgmt_iface="enp9s0f0", confirm_timeout=3600
    )
    app = create_app(config_dir=tmp_path, network_manager=manager)
    client = TestClient(app, base_url="https://testserver")
    client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    return client, calls


def item(**kwargs):
    base = {"name": "enp5s0", "role": "wan", "ipv4": "dhcp"}
    base.update(kwargs)
    return base


def test_requires_auth(tmp_path):
    app = create_app(config_dir=tmp_path)
    client = TestClient(app, base_url="https://testserver")
    assert client.get("/api/network/interfaces/config").status_code == 401


def test_initial_config(env):
    client, _ = env
    resp = client.get("/api/network/interfaces/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == {}
    assert body["management"] == "enp9s0f0"
    assert body["pending"] is None


def test_apply_and_confirm(env):
    client, calls = env
    resp = client.put(
        "/api/network/interfaces/config", json={"items": {"enp5s0": item(dns=["1.1.1.1"])}}
    )
    assert resp.status_code == 200
    assert resp.json()["pending"]["username"] == "admin"
    assert len(calls) == 1

    assert client.post("/api/network/interfaces/confirm").status_code == 200
    body = client.get("/api/network/interfaces/config").json()
    assert body["items"]["enp5s0"]["role"] == "wan"
    assert body["pending"] is None
    assert client.post("/api/network/interfaces/confirm").status_code == 409


def test_apply_rejects_management_iface(env):
    client, calls = env
    resp = client.put(
        "/api/network/interfaces/config",
        json={"items": {"enp9s0f0": item(name="enp9s0f0")}},
    )
    assert resp.status_code == 400
    assert "управляющий" in resp.json()["detail"]
    assert calls == []


def test_apply_rejects_invalid_static(env):
    client, _ = env
    resp = client.put(
        "/api/network/interfaces/config",
        json={"items": {"enp5s0": item(ipv4="static", address="192.168.1.2/24")}},
    )
    assert resp.status_code == 422
    assert "шлюз" in resp.json()["detail"][0]["msg"]


def test_apply_conflict_while_pending(env):
    client, _ = env
    first = client.put("/api/network/interfaces/config", json={"items": {"enp5s0": item()}})
    assert first.status_code == 200
    resp = client.put(
        "/api/network/interfaces/config", json={"items": {"enp6s0": item(name="enp6s0")}}
    )
    assert resp.status_code == 409
    assert client.post("/api/network/interfaces/rollback").status_code == 200


def test_rollback_keeps_committed_state(env):
    client, _ = env
    client.put("/api/network/interfaces/config", json={"items": {"enp5s0": item()}})
    resp = client.post("/api/network/interfaces/rollback")
    assert resp.status_code == 200 and resp.json()["ok"] is True
    body = client.get("/api/network/interfaces/config").json()
    assert body["items"] == {}
    assert body["pending"] is None


def test_status_endpoint(env):
    client, _ = env
    body = client.get("/api/network/interfaces/status").json()
    assert body["pending"] is None
    assert body["confirm_timeout"] == 3600
    client.put("/api/network/interfaces/config", json={"items": {"enp5s0": item()}})
    body = client.get("/api/network/interfaces/status").json()
    assert body["pending"]["seconds_left"] > 0


# ---------- этап 3: сегменты, маршруты, политики WAN ----------

SEGMENT = {
    "id": "home",
    "name": "Домашняя",
    "interfaces": ["enp7s0"],
    "address": "192.168.10.1/24",
    "dhcp": {
        "enabled": True,
        "pool_start": "192.168.10.50",
        "pool_end": "192.168.10.150",
        "lease_hours": 12,
        "dns": [],
    },
    "reservations": [],
}


def setup_router(env):
    """WAN + LAN интерфейсы, подтверждённые: база для сегментов."""
    client, _ = env
    lan = item(name="enp7s0", role="lan", ipv4="static", address="192.168.30.1/24")
    client.put("/api/network/interfaces/config", json={"items": {"enp5s0": item(), "enp7s0": lan}})
    assert client.post("/api/network/interfaces/confirm").status_code == 200
    return client


def test_snapshot_includes_new_sections(env):
    client, _ = env
    body = client.get("/api/network/interfaces/config").json()
    assert body["segments"] == []
    assert body["routes"] == []
    assert body["wan"] == {"policies": {}, "mode": "failover"}


def test_segments_apply_and_confirm(env):
    client, calls = env
    setup_router(env)
    resp = client.put("/api/network/segments", json={"segments": [SEGMENT]})
    assert resp.status_code == 200
    assert resp.json()["pending"]["sections"]["segments"][0]["id"] == "home"
    assert client.post("/api/network/interfaces/confirm").status_code == 200
    body = client.get("/api/network/interfaces/config").json()
    assert body["segments"][0]["id"] == "home"
    staging = client.app.state.network.staging_dir
    assert (staging / "altrouter-arbr-home.netdev").exists()
    assert (staging / "dnsmasq.conf").exists()
    assert len(calls) == 2


def test_segments_reject_non_lan_port(env):
    client, _ = env
    setup_router(env)
    resp = client.put(
        "/api/network/segments", json={"segments": [{**SEGMENT, "interfaces": ["enp5s0"]}]}
    )
    assert resp.status_code == 400
    assert "LAN" in resp.json()["detail"]


def test_wan_policy_apply_and_status(env):
    client, _ = env
    setup_router(env)
    policy = {
        "priority": 1,
        "ping_check": {
            "enabled": True,
            "target": "1.1.1.1",
            "interval_s": 30,
            "fail_threshold": 3,
        },
    }
    resp = client.put("/api/network/wan", json={"policies": {"enp5s0": policy}})
    assert resp.status_code == 200
    assert client.post("/api/network/interfaces/confirm").status_code == 200
    body = client.get("/api/network/interfaces/config").json()
    assert body["wan"]["policies"]["enp5s0"]["priority"] == 1

    status = client.get("/api/network/wan/status").json()
    # слушатель состояния настроил PingChecker уже при применении (без lifespan-потока)
    assert status["items"]["enp5s0"]["target"] == "1.1.1.1"
    assert status["items"]["enp5s0"]["state"] == "unknown"


def test_wan_policy_rejects_non_wan_iface(env):
    client, _ = env
    setup_router(env)
    resp = client.put(
        "/api/network/wan", json={"policies": {"enp7s0": {"priority": 1}}}
    )
    assert resp.status_code == 400
    assert "WAN" in resp.json()["detail"]


def test_routes_reject_unknown_gateway(env):
    client, _ = env
    setup_router(env)
    resp = client.put(
        "/api/network/routes",
        json={"routes": [{"dest": "10.5.0.0/16", "gateway": "172.16.0.1"}]},
    )
    assert resp.status_code == 400
    assert "подсеть" in resp.json()["detail"]


def test_section_conflict_returns_409(env):
    client, _ = env
    setup_router(env)
    assert client.put("/api/network/segments", json={"segments": [SEGMENT]}).status_code == 200
    resp = client.put("/api/network/wan", json={"policies": {"enp5s0": {"priority": 1}}})
    assert resp.status_code == 409
    assert client.post("/api/network/interfaces/rollback").status_code == 200


def test_wan_status_requires_auth(tmp_path):
    app = create_app(config_dir=tmp_path)
    client = TestClient(app, base_url="https://testserver")
    assert client.get("/api/network/wan/status").status_code == 401


# ---------- этап 4: файрвол, переадресация портов, локальные имена ----------


def apply_segment(env):
    """База этапа 4: WAN+LAN подтверждены, есть сегмент home (192.168.10.1/24)."""
    client, _ = env
    setup_router(env)
    resp = client.put("/api/network/segments", json={"segments": [SEGMENT]})
    assert resp.status_code == 200
    assert client.post("/api/network/interfaces/confirm").status_code == 200
    return client


def test_snapshot_includes_stage4_sections(env):
    client, _ = env
    body = client.get("/api/network/interfaces/config").json()
    assert body["rules"] == []
    assert body["forwards"] == []
    assert body["dns"] == []


def test_firewall_apply_and_confirm(env):
    client, calls = env
    apply_segment(env)
    rule = {
        "direction": "forward",
        "zone": "home",
        "proto": "tcp",
        "dst_ip": "192.168.10.0/24",
        "dst_port": "445",
        "action": "drop",
        "comment": "smb",
    }
    resp = client.put("/api/network/firewall", json={"rules": [rule]})
    assert resp.status_code == 200
    assert resp.json()["pending"]["sections"]["rules"][0]["comment"] == "smb"
    assert client.post("/api/network/interfaces/confirm").status_code == 200
    body = client.get("/api/network/interfaces/config").json()
    assert body["rules"][0]["zone"] == "home"
    nft = (client.app.state.network.staging_dir / "nftables.conf").read_text(encoding="utf-8")
    assert 'ip daddr 192.168.10.0/24 drop comment "правило 1 (smb)"' in nft
    assert len(calls) == 3


def test_firewall_rejects_unknown_zone(env):
    client, _ = env
    apply_segment(env)
    resp = client.put("/api/network/firewall", json={"rules": [{"zone": "guest"}]})
    assert resp.status_code == 400
    assert "сегмент" in resp.json()["detail"]


def test_forwards_apply_and_dnat_in_staging(env):
    client, calls = env
    apply_segment(env)
    fw = {"proto": "tcp", "port": "8080", "to_ip": "192.168.10.50", "to_port": "80"}
    resp = client.put("/api/network/forwards", json={"forwards": [fw]})
    assert resp.status_code == 200
    assert client.post("/api/network/interfaces/confirm").status_code == 200
    nft = (client.app.state.network.staging_dir / "nftables.conf").read_text(encoding="utf-8")
    assert 'dnat to 192.168.10.50:80 comment "DNAT tcp/8080"' in nft
    assert 'oifname "arbr-home" ip daddr 192.168.10.50 tcp dport 80 accept' in nft
    assert len(calls) == 3


def test_forwards_reject_target_outside_subnets(env):
    client, _ = env
    apply_segment(env)
    resp = client.put(
        "/api/network/forwards",
        json={"forwards": [{"proto": "tcp", "port": "80", "to_ip": "10.9.9.9"}]},
    )
    assert resp.status_code == 400
    assert "не входит ни в одну известную подсеть" in resp.json()["detail"]


def test_dns_apply_and_host_record(env):
    client, _ = env
    apply_segment(env)
    rec = {"hostname": "nas", "ip": "192.168.10.20", "comment": "хранилище"}
    resp = client.put("/api/network/dns", json={"records": [rec]})
    assert resp.status_code == 200
    assert client.post("/api/network/interfaces/confirm").status_code == 200
    body = client.get("/api/network/interfaces/config").json()
    assert body["dns"][0]["hostname"] == "nas"
    conf = (client.app.state.network.staging_dir / "dnsmasq.conf").read_text(encoding="utf-8")
    assert "host-record=nas,192.168.10.20 # хранилище" in conf


def test_dns_rejects_foreign_ip(env):
    client, _ = env
    apply_segment(env)
    resp = client.put("/api/network/dns", json={"records": [{"hostname": "nas", "ip": "8.8.8.8"}]})
    assert resp.status_code == 400
    assert "не входит ни в одну известную подсеть" in resp.json()["detail"]
