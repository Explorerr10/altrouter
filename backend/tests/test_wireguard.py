"""Этап 5: модели WireGuard, рендер networkd/nftables, валидация, API."""

import subprocess

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.network.composer import (
    compose_staging,
    render_nftables,
    render_wg_netdev,
    render_wg_network,
)
from app.network.errors import NetworkError
from app.network.manager import InterfaceManager
from app.network.segments import SegmentConfig
from app.network.wireguard import (
    WireguardInterface,
    WireguardPeer,
    generate_keypair,
    render_client_config,
)

KEY = "A" * 43 + "="
KEY2 = "B" * 43 + "="


def iface(**kwargs):
    base = {
        "id": "home",
        "name": "Дом",
        "address": "10.9.0.1/24",
        "listen_port": 51820,
        "private_key": KEY,
        "peers": [peer()],
    }
    base.update(kwargs)
    return WireguardInterface(**base)


def peer(**kwargs):
    base = {
        "name": "phone",
        "public_key": KEY2,
        "allowed_ips": ["10.9.0.2/32"],
        "endpoint": "wg.example.com:51820",
    }
    base.update(kwargs)
    return WireguardPeer(**base)


# ---------- модели ----------


def test_peer_requires_key_or_private():
    with pytest.raises(ValueError, match="публичный ключ или сгенерируйте"):
        WireguardPeer(name="x", allowed_ips=["10.0.0.2/32"])
    p = WireguardPeer(name="x", private_key=KEY, allowed_ips=["10.0.0.2"])
    assert p.public_key is None and p.allowed_ips == ["10.0.0.2/32"]


def test_peer_bad_key_and_allowed():
    with pytest.raises(ValueError, match="Некорректный публичный ключ"):
        peer(public_key="short")
    with pytest.raises(ValueError, match="Allowed IP"):
        peer(allowed_ips=["999.1.1.1/32"])
    with pytest.raises(ValueError, match="повторяются"):
        peer(allowed_ips=["10.0.0.2/32", "10.0.0.2"])


def test_iface_validation():
    iface(route_mode="all", priority=1)
    with pytest.raises(ValueError, match="приоритет от 1 до 99"):
        iface(route_mode="all")
    with pytest.raises(ValueError, match="выбранные устройства"):
        iface(route_mode="devices", devices=[])
    with pytest.raises(ValueError, match="уже используется"):
        iface(peers=[peer(), peer(name="two")])
    with pytest.raises(ValueError, match="назначен другому пиру"):
        iface(peers=[peer(), peer(name="two", public_key=KEY, allowed_ips=["10.9.0.2/32"])])
    with pytest.raises(ValueError, match="Идентификатор"):
        iface(id="Плохой!")


def test_devices_cleared_for_other_modes():
    assert iface(route_mode="none", devices=["192.168.1.5"]).devices == []


# ---------- ключи и статус ----------


def test_generate_keypair(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        out = "PUB\n" if cmd == ["wg", "pubkey"] else KEY + "\n"
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    private, public = generate_keypair()
    assert private == KEY and public == "PUB"
    assert ["wg", "genkey"] == calls[0] and ["wg", "pubkey"] == calls[1]


# ---------- рендер networkd ----------


def test_render_wg_netdev():
    w = iface(
        route_mode="all",
        priority=1,
        peers=[peer(preshared_key=KEY, keepalive=25, comment="телефон")],
    )
    text = render_wg_netdev(w)
    assert "[NetDev]\nName=arwg-home\nKind=wireguard" in text
    assert "[WireGuard]\nListenPort=51820\nFwMark=51820\nPrivateKey=" + KEY in text
    assert "PublicKey=" + KEY2 in text
    assert "AllowedIPs=10.9.0.2/32" in text
    assert "PresharedKey=" + KEY in text
    assert "Endpoint=wg.example.com:51820" in text
    assert "PersistentKeepalive=25" in text
    assert "#phone (телефон)" in text
    assert "FwMark" not in render_wg_netdev(iface(route_mode="none"))


def test_render_wg_network_modes():
    none_text = render_wg_network(iface(route_mode="none"))
    assert "Address=10.9.0.1/24" in none_text and "IPForward=ipv4" in none_text
    assert "[Route]" not in none_text

    all_text = render_wg_network(iface(route_mode="all", priority=1))
    assert "[Route]\nDestination=0.0.0.0/0\nTable=51820" in all_text
    assert "[RoutingPolicyRule]\nFirewallMark=51820\nTable=main\nPriority=10" in all_text
    assert "[RoutingPolicyRule]\nSuppressPrefixLength=0\nTable=main\nPriority=15" in all_text
    assert "[RoutingPolicyRule]\nTable=51820\nPriority=101" in all_text

    devices_text = render_wg_network(
        iface(route_mode="devices", priority=2, devices=["192.168.10.55/32"]),
        devices=[("192.168.10.55/32", "192.168.10.0/24")],
    )
    assert "[RoutingPolicyRule]\nFrom=192.168.10.55/32\nFirewallMark=51820" in devices_text
    assert "From=192.168.10.55/32\nSuppressPrefixLength=0" in devices_text
    assert "From=192.168.10.55/32\nTable=51820\nPriority=102" in devices_text


def test_render_client_config():
    w = iface(mtu=1420, public_key=KEY2, endpoint="wg.example.com")
    text = render_client_config(w, peer(private_key=KEY))
    assert f"PrivateKey = {KEY}" in text
    assert "Address = 10.9.0.2/32" in text
    assert "MTU = 1420" in text
    assert f"PublicKey = {KEY2}" in text
    assert "Endpoint = wg.example.com:51820" in text
    assert "AllowedIPs = 0.0.0.0/0" in text
    with pytest.raises(ValueError, match="недоступен"):
        render_client_config(w, peer())


# ---------- валидация состояния ----------


def test_validate_wireguard_section(tmp_path):
    from app.network.models import InterfaceConfig

    manager = InterfaceManager(tmp_path, applier=lambda: None, mgmt_iface="enp9s0f0")
    manager.apply_sections({"wireguard": [iface()]}, "admin")
    manager.confirm()
    with pytest.raises(NetworkError, match="порт 51820 дважды"):
        manager.apply_sections({"wireguard": [iface(), iface(id="work")]}, "admin")
    with pytest.raises(NetworkError, match="пересекается"):
        manager.apply_sections(
            {"wireguard": [iface(), iface(id="work", address="10.9.0.5/24", listen_port=51821)]},
            "admin",
        )
    seg = SegmentConfig(
        id="lan", name="LAN", interfaces=["enp7s0"], address="192.168.10.1/24"
    )
    items = {
        "enp7s0": InterfaceConfig(
            name="enp7s0", role="lan", ipv4="static", address="192.168.10.2/24"
        )
    }
    with pytest.raises(NetworkError, match="не входит ни в одну известную подсеть"):
        manager.apply_sections(
            {
                "items": items,
                "segments": [seg],
                "wireguard": [iface(route_mode="devices", devices=["10.5.5.5"])],
            },
            "admin",
        )
    manager.apply_sections(
        {
            "items": items,
            "segments": [seg],
            "wireguard": [iface(route_mode="devices", devices=["192.168.10.55"])],
        },
        "admin",
    )


# ---------- nftables и staging ----------


def nft_state(wg_items):
    from app.network.models import InterfaceConfig
    from app.network.segments import WanConfig

    return {
        "items": {"enp5s0": InterfaceConfig(name="enp5s0", role="wan", ipv4="dhcp")},
        "segments": [
            SegmentConfig(id="lan", name="LAN", interfaces=["enp7s0"], address="192.168.10.1/24")
        ],
        "routes": [],
        "wan": WanConfig(policies={}),
        "wireguard": wg_items,
    }


def test_render_nftables_wireguard():
    text = render_nftables(
        nft_state([iface(route_mode="devices", devices=["192.168.10.55/32"])]), "enp9s0f0"
    )
    assert 'iifname "enp5s0" udp dport 51820 accept comment "WireGuard home"' in text
    assert 'oifname "arwg-home" accept comment "сегмент' in text
    assert 'iifname "arwg-home" oifname "arbr-lan" accept' in text
    assert 'iifname "arwg-home" oifname "enp5s0" accept' in text
    assert 'ip saddr 192.168.10.55/32 oifname "arwg-home" accept' in text
    assert 'ip saddr 10.9.0.2/32 oifname "enp5s0" masquerade' in text
    assert 'ip saddr 192.168.10.55/32 oifname "arwg-home" masquerade' in text
    disabled = render_nftables(nft_state([iface(enabled=False)]), "enp9s0f0")
    assert "arwg-home" not in disabled


def test_compose_staging_wireguard(tmp_path):
    compose_staging(tmp_path, nft_state([iface()]), "enp9s0f0")
    assert (tmp_path / "altrouter-arwg-home.netdev").read_text(encoding="utf-8").startswith("#")
    network = (tmp_path / "altrouter-arwg-home.network").read_text(encoding="utf-8")
    assert "Name=arwg-home" in network


# ---------- API ----------


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr("app.network.wireguard.generate_keypair", lambda: (KEY, KEY2))
    monkeypatch.setattr("app.network.wireguard.derive_public", lambda private: KEY2)
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


def payload(**kwargs):
    base = {
        "id": "home",
        "name": "Дом",
        "address": "10.9.0.1/24",
        "listen_port": 51820,
        "endpoint": "wg.example.com:51820",
        "peers": [
            {
                "name": "phone",
                "public_key": KEY2,
                "allowed_ips": ["10.9.0.2/32"],
                "private_key": KEY,
            }
        ],
    }
    base.update(kwargs)
    return {"items": [base]}


def test_vpn_requires_auth(tmp_path):
    client = TestClient(create_app(config_dir=tmp_path), base_url="https://testserver")
    assert client.get("/api/network/vpn/status").status_code == 401
    assert client.put("/api/network/vpn/wireguard", json=payload()).status_code == 401


def test_vpn_put_and_snapshot(env):
    client, calls = env
    resp = client.put("/api/network/vpn/wireguard", json=payload(private_key=""))
    assert resp.status_code == 200
    assert calls == [1]
    assert client.post("/api/network/interfaces/confirm").status_code == 200
    cfg = client.get("/api/network/interfaces/config").json()
    wg = cfg["wireguard"][0]
    assert wg["private_key"] == KEY and wg["public_key"] == KEY2


def test_vpn_dup_id(env):
    client, _ = env
    body = payload()
    body["items"].append(dict(body["items"][0]))
    resp = client.put("/api/network/vpn/wireguard", json=body)
    assert resp.status_code == 400 and "повторяется" in resp.json()["detail"]


def test_vpn_peer_export(env):
    client, _ = env
    client.put("/api/network/vpn/wireguard", json=payload())
    resp = client.get("/api/network/vpn/wireguard/home/peer/phone/config")
    assert resp.status_code == 200
    assert "PrivateKey = " + KEY in resp.text
    assert client.get("/api/network/vpn/wireguard/home/peer/none/config").status_code == 404
    imported = payload(
        peers=[{"name": "pc", "public_key": KEY2, "allowed_ips": ["10.9.0.3/32"]}]
    )
    client.post("/api/network/interfaces/rollback")
    client.put("/api/network/vpn/wireguard", json=imported)
    resp = client.get("/api/network/vpn/wireguard/home/peer/pc/config")
    assert resp.status_code == 400 and "недоступен" in resp.json()["detail"]


def test_vpn_keypair_and_status(env):
    client, _ = env
    resp = client.get("/api/network/vpn/keypair")
    assert resp.status_code == 200
    assert resp.json() == {"private_key": KEY, "public_key": KEY2}
    assert client.get("/api/network/vpn/status").status_code == 200
