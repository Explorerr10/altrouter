from pathlib import Path

import pytest

from app.network.composer import (
    bridge_name,
    compose_staging,
    render_bridge_netdev,
    render_bridge_network,
    render_slave_network,
    render_wan,
    resolve_route_egress,
    validate_state,
)
from app.network.errors import NetworkError
from app.network.generator import render_network
from app.network.models import InterfaceConfig
from app.network.segments import (
    DhcpSettings,
    PingCheck,
    Reservation,
    SegmentConfig,
    StaticRoute,
    WanConfig,
    WanPolicy,
)

MGMT = "enp9s0f0"


# ---------- модели: резервы и DHCP ----------

def test_reservation_normalizes_mac_and_ip():
    res = Reservation(mac="AA-BB-CC-DD-EE-FF", ip=" 192.168.10.50 ")
    assert res.mac == "aa:bb:cc:dd:ee:ff"
    assert res.ip == "192.168.10.50"


def test_reservation_rejects_bad_mac_and_ip():
    with pytest.raises(ValueError, match="MAC"):
        Reservation(mac="11:22:33", ip="192.168.10.5")
    with pytest.raises(ValueError, match="IP"):
        Reservation(mac="11:22:33:44:55:66", ip="300.1.1.1")


def test_dhcp_lease_bounds():
    assert DhcpSettings().lease_hours == 12
    with pytest.raises(ValueError, match="аренд"):
        DhcpSettings(lease_hours=0)


# ---------- модели: сегменты ----------

def segment(**kwargs) -> SegmentConfig:
    base = {
        "id": "home",
        "name": "Домашняя",
        "interfaces": ["enp5s0"],
        "address": "192.168.10.1/24",
        "dhcp": DhcpSettings(
            enabled=True, pool_start="192.168.10.50", pool_end="192.168.10.150"
        ),
        "reservations": [Reservation(mac="11:22:33:44:55:66", ip="192.168.10.7", hostname="nas")],
    }
    base.update(kwargs)
    return SegmentConfig(**base)


def test_segment_valid_normalizes_address():
    seg = segment(address="192.168.10.1/255.255.255.0")
    assert seg.address == "192.168.10.1/24"


def test_segment_id_and_name_rules():
    with pytest.raises(ValueError, match="Идентификатор"):
        segment(id="Home")
    with pytest.raises(ValueError, match="Идентификатор"):
        segment(id="verylongsegmentid")
    with pytest.raises(ValueError, match="Название"):
        segment(name="   ")


def test_segment_requires_ports_without_dupes():
    with pytest.raises(ValueError, match="LAN-порт"):
        segment(interfaces=[])
    with pytest.raises(ValueError, match="повторяться"):
        segment(interfaces=["enp5s0", "enp5s0"])


def test_segment_bad_address():
    with pytest.raises(ValueError, match="адрес"):
        segment(address="192.168.10.300/24")
    with pytest.raises(ValueError, match="IPv4"):
        segment(address="fd00::1/64")


def test_segment_pool_validation():
    with pytest.raises(ValueError, match="границы пула"):
        segment(dhcp=DhcpSettings(enabled=True))
    with pytest.raises(ValueError, match="вне подсети"):
        segment(dhcp=DhcpSettings(enabled=True, pool_start="10.0.0.10", pool_end="192.168.10.150"))
    with pytest.raises(ValueError, match="меньше конца"):
        segment(
            dhcp=DhcpSettings(enabled=True, pool_start="192.168.10.50", pool_end="192.168.10.20")
        )
    with pytest.raises(ValueError, match="Пул не должен"):
        segment(
            dhcp=DhcpSettings(enabled=True, pool_start="192.168.10.1", pool_end="192.168.10.150")
        )
    with pytest.raises(ValueError, match="Пул не должен"):
        segment(
            dhcp=DhcpSettings(enabled=True, pool_start="192.168.10.200", pool_end="192.168.10.255")
        )


def test_segment_reservation_validation():
    with pytest.raises(ValueError, match="вне подсети"):
        segment(reservations=[Reservation(mac="11:22:33:44:55:66", ip="10.9.9.9")])
    with pytest.raises(ValueError, match="дважды"):
        segment(
            reservations=[
                Reservation(mac="11:22:33:44:55:66", ip="192.168.10.7"),
                Reservation(mac="11:22:33:44:55:66", ip="192.168.10.8"),
            ]
        )


# ---------- модели: маршруты и политики WAN ----------

def test_static_route_normalizes_dest():
    route = StaticRoute(dest="10.5.9.7/16", gateway="192.168.1.1")
    assert route.dest == "10.5.0.0/16"
    assert route.iface is None and route.metric is None


def test_static_route_rejects_bad():
    with pytest.raises(ValueError, match="подсет"):
        StaticRoute(dest="10.5.0.0/33", gateway="192.168.1.1")
    with pytest.raises(ValueError, match="шлюз"):
        StaticRoute(dest="10.5.0.0/16", gateway="boom")
    with pytest.raises(ValueError, match="Метрик"):
        StaticRoute(dest="10.5.0.0/16", gateway="192.168.1.1", metric=0)


def test_ping_check_target_and_bounds():
    assert PingCheck().target == "1.1.1.1"
    assert PingCheck(target="isp-check.example.com").target == "isp-check.example.com"
    with pytest.raises(ValueError, match="цель"):
        PingCheck(target="bad host!")
    with pytest.raises(ValueError, match="Интервал"):
        PingCheck(interval_s=1)
    with pytest.raises(ValueError, match="Порог"):
        PingCheck(fail_threshold=99)


def test_wan_policy_metric():
    assert WanPolicy().route_metric is None
    assert WanPolicy(priority=1).route_metric == 100
    assert WanPolicy(priority=7).route_metric == 700
    with pytest.raises(ValueError, match="Приоритет"):
        WanPolicy(priority=0)


def test_wan_config_metric_for():
    wan = WanConfig(policies={"enp5s0": WanPolicy(priority=2)})
    assert wan.metric_for("enp5s0") == 200
    assert wan.metric_for("enp6s0") is None


# ---------- композер: рендер networkd ----------

def wan_dhcp(name="enp5s0") -> InterfaceConfig:
    return InterfaceConfig(name=name, role="wan", ipv4="dhcp")


def wan_static(name="enp6s0") -> InterfaceConfig:
    return InterfaceConfig(
        name=name, role="wan", ipv4="static", address="192.168.1.2/24", gateway="192.168.1.1"
    )


def test_render_wan_without_metric_matches_generator():
    assert render_wan(wan_dhcp(), None) == render_network(wan_dhcp())
    assert render_wan(wan_static(), None) == render_network(wan_static())


def test_render_wan_dhcp_with_metric():
    text = render_wan(wan_dhcp(), 300)
    assert "[DHCP]" in text and "ClientIdentifier=mac" in text
    assert "RouteMetric=300" in text
    assert text.index("ClientIdentifier=mac") < text.index("RouteMetric=300")


def test_render_wan_static_with_metric():
    text = render_wan(wan_static(), 200)
    assert "Gateway=192.168.1.1" in text
    assert "[Route]" in text and "Metric=200" in text
    network_block = text.split("[Route]")[0]
    assert "Gateway=" not in network_block


def test_render_slave_and_bridge():
    assert 'Bridge=arbr-home' in render_slave_network("enp5s0", "arbr-home")
    netdev = render_bridge_netdev("arbr-home")
    assert "Name=arbr-home" in netdev and "Kind=bridge" in netdev
    bridge_net = render_bridge_network(segment(), [])
    assert "Name=arbr-home" in bridge_net and "Address=192.168.10.1/24" in bridge_net


# ---------- композер: перекрёстная валидация ----------

def state(**overrides) -> dict:
    lan = InterfaceConfig(name="enp7s0", role="lan", ipv4="static", address="192.168.30.1/24")
    base = {
        "items": {"enp5s0": wan_dhcp(), "enp7s0": lan},
        "segments": [],
        "routes": [],
        "wan": WanConfig(),
    }
    base.update(overrides)
    return base


def test_validate_accepts_consistent_state():
    validate_state(
        state(
            items={
                "enp5s0": wan_dhcp(),
                "enp7s0": InterfaceConfig(
                    name="enp7s0", role="lan", ipv4="static", address="192.168.30.1/24"
                ),
            },
            segments=[segment(interfaces=["enp7s0"], address="192.168.10.1/24")],
            routes=[StaticRoute(dest="10.5.0.0/16", gateway="192.168.10.1")],
            wan=WanConfig(policies={"enp5s0": WanPolicy(priority=1)}),
        ),
        mgmt=MGMT,
    )


def test_validate_rejects_management_iface():
    with pytest.raises(NetworkError, match="управляющий"):
        items = {
            "enp9s0f0": wan_dhcp(name="enp9s0f0"),
            "enp7s0": InterfaceConfig(
                name="enp7s0", role="lan", ipv4="static", address="192.168.30.1/24"
            ),
        }
        validate_state(state(items=items), mgmt=MGMT)


def test_validate_segment_port_must_be_lan():
    with pytest.raises(NetworkError, match="не назначен LAN-ролью"):
        validate_state(state(segments=[segment(interfaces=["enp5s0"])]), mgmt=MGMT)


def test_validate_port_in_two_segments():
    second = segment(
        id="off2",
        name="Второй",
        interfaces=["enp7s0"],
        address="192.168.40.1/24",
        dhcp=DhcpSettings(),
        reservations=[],
    )
    with pytest.raises(NetworkError, match="несколько сегментов"):
        validate_state(
            state(
                segments=[
                    segment(interfaces=["enp7s0"], address="192.168.10.1/24"),
                    second,
                ]
            ),
            mgmt=MGMT,
        )


def test_validate_overlapping_subnets():
    with pytest.raises(NetworkError, match="пересекаются"):
        validate_state(
            state(
                items={
                    "enp5s0": wan_static(name="enp5s0"),
                    "enp6s0": wan_static(name="enp6s0"),
                },
                segments=[],
            ),
            mgmt=MGMT,
        )


def test_validate_route_gateway_unknown():
    with pytest.raises(NetworkError, match="не входит ни в одну"):
        validate_state(
            state(routes=[StaticRoute(dest="10.5.0.0/16", gateway="172.16.0.1")]), mgmt=MGMT
        )


def test_validate_wan_policy_requires_wan_role():
    with pytest.raises(NetworkError, match="не является WAN"):
        validate_state(
            state(wan=WanConfig(policies={"enp7s0": WanPolicy(priority=1)})), mgmt=MGMT
        )


def test_resolve_route_egress():
    lan = InterfaceConfig(name="enp7s0", role="lan", ipv4="static", address="192.168.30.1/24")
    items = {"enp5s0": wan_static(), "enp7s0": lan}
    route = StaticRoute(dest="10.0.0.0/8", gateway="192.168.1.1")
    assert resolve_route_egress(route, items, []) == "enp5s0"
    segs = [segment(interfaces=["enp7s0"], address="192.168.10.1/24")]
    assert (
        resolve_route_egress(StaticRoute(dest="10.0.0.0/8", gateway="192.168.10.1"), items, segs)
        == "arbr-home"
    )
    with pytest.raises(NetworkError, match="а не через"):
        resolve_route_egress(
            StaticRoute(dest="10.0.0.0/8", gateway="192.168.1.1", iface="arbr-home"), items, segs
        )


# ---------- композер: полный staging ----------

def full_state() -> dict:
    lan = InterfaceConfig(name="enp7s0", role="lan", ipv4="static", address="192.168.30.1/24")
    return {
        "items": {
            "enp5s0": wan_dhcp(),
            "enp6s0": InterfaceConfig(name="enp6s0", role="off"),
            "enp7s0": lan,
        },
        "segments": [segment(interfaces=["enp7s0"], address="192.168.10.1/24")],
        "routes": [StaticRoute(dest="10.5.0.0/16", gateway="192.168.10.1")],
        "wan": WanConfig(policies={"enp5s0": WanPolicy(priority=1)}),
    }


def test_compose_staging_full(tmp_path: Path):
    compose_staging(tmp_path, full_state(), mgmt=MGMT)
    assert (tmp_path / "altrouter-enp5s0.network").exists()
    assert not (tmp_path / "altrouter-enp6s0.network").exists()  # off — без файла
    slave = (tmp_path / "altrouter-enp7s0.network").read_text(encoding="utf-8")
    assert "Bridge=arbr-home" in slave and "Address=" not in slave
    assert (tmp_path / "altrouter-arbr-home.netdev").exists()
    bridge = (tmp_path / "altrouter-arbr-home.network").read_text(encoding="utf-8")
    assert "Address=192.168.10.1/24" in bridge
    assert "[Route]" in bridge and "Destination=10.5.0.0/16" in bridge  # маршрут ушёл на мост
    wan_text = (tmp_path / "altrouter-enp5s0.network").read_text(encoding="utf-8")
    assert "RouteMetric=100" in wan_text

    dnsmasq = (tmp_path / "dnsmasq.conf").read_text(encoding="utf-8")
    assert "interface=arbr-home" in dnsmasq
    assert "dhcp-range=set:home,192.168.10.50,192.168.10.150,12h" in dnsmasq
    assert "dhcp-host=11:22:33:44:55:66,192.168.10.7,nas" in dnsmasq
    assert "server=1.1.1.1" in dnsmasq  # DNS не заданы на WAN — дефолт

    nft = (tmp_path / "nftables.conf").read_text(encoding="utf-8")
    assert 'iifname "enp9s0f0" accept' in nft
    assert 'iifname "arbr-home" oifname "enp5s0" accept' in nft
    assert 'ip saddr 192.168.10.0/24 oifname "enp5s0" masquerade' in nft
    assert "policy drop;" in nft


def test_compose_staging_cleanup_and_empty(tmp_path: Path):
    compose_staging(tmp_path, full_state(), mgmt=MGMT)
    assert (tmp_path / "altrouter-arbr-home.netdev").exists()
    compose_staging(tmp_path, _parse_empty(), mgmt=MGMT)
    assert not (tmp_path / "altrouter-arbr-home.netdev").exists()
    assert not (tmp_path / "altrouter-enp5s0.network").exists()
    dnsmasq = (tmp_path / "dnsmasq.conf").read_text(encoding="utf-8")
    assert "port=0" in dnsmasq
    nft = (tmp_path / "nftables.conf").read_text(encoding="utf-8")
    assert 'iifname "enp9s0f0" accept' in nft
    assert "masquerade" not in nft


def _parse_empty() -> dict:
    from app.network.manager import _parse_state

    return _parse_state({})


def test_dnsmasq_uses_wan_dns_when_configured():
    st = full_state()
    st["items"]["enp5s0"] = InterfaceConfig(
        name="enp5s0", role="wan", ipv4="static",
        address="192.168.1.2/24", gateway="192.168.1.1", dns=["8.8.8.8"],
    )
    from app.network.composer import render_dnsmasq

    text = render_dnsmasq(st)
    assert "server=8.8.8.8" in text
    assert "server=1.1.1.1" not in text


def test_bridge_name():
    assert bridge_name("home") == "arbr-home"
