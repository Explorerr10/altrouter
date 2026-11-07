import asyncio
import json
import time
from pathlib import Path

import pytest

from app.network.composer import compose_staging, validate_state
from app.network.errors import ApplyError, NetworkError
from app.network.generator import network_file_name, render_network
from app.network.manager import InterfaceManager
from app.network.models import InterfaceConfig
from app.network.segments import DhcpSettings, SegmentConfig, StaticRoute, WanConfig, WanPolicy

MGMT = "enp9s0f0"


def cfg(**kwargs) -> InterfaceConfig:
    return InterfaceConfig(**kwargs)


# ---------- модели ----------

def test_wan_dhcp_minimal():
    item = cfg(name="enp5s0", role="wan", ipv4="dhcp")
    assert item.dns == []
    assert item.address is None


def test_wan_static_normalizes_address_and_dns():
    item = cfg(
        name="enp5s0",
        role="wan",
        ipv4="static",
        address="192.168.1.2/24",
        gateway="192.168.1.1",
        dns=["1.1.1.1", " 8.8.8.8 "],
    )
    assert item.address == "192.168.1.2/24"
    assert item.dns == ["1.1.1.1", "8.8.8.8"]


def test_wan_static_requires_gateway():
    with pytest.raises(ValueError, match="шлюз"):
        cfg(name="enp5s0", role="wan", ipv4="static", address="192.168.1.2/24")


def test_wan_static_requires_prefix():
    with pytest.raises(ValueError, match="префикс"):
        cfg(name="enp5s0", role="wan", ipv4="static", address="192.168.1.2", gateway="192.168.1.1")


def test_wan_gateway_outside_subnet_rejected():
    with pytest.raises(ValueError, match="подсет"):
        cfg(
            name="enp5s0",
            role="wan",
            ipv4="static",
            address="192.168.1.2/24",
            gateway="10.0.0.1",
        )


def test_wan_dhcp_forbids_address():
    with pytest.raises(ValueError, match="DHCP"):
        cfg(name="enp5s0", role="wan", ipv4="dhcp", address="192.168.1.2/24")


def test_lan_requires_static():
    with pytest.raises(ValueError, match="LAN"):
        cfg(name="enp7s0", role="lan", ipv4="dhcp")


def test_lan_forbids_gateway_and_dns():
    with pytest.raises(ValueError, match="шлюз"):
        cfg(
            name="enp7s0",
            role="lan",
            ipv4="static",
            address="192.168.10.1/24",
            gateway="192.168.10.1",
        )
    with pytest.raises(ValueError, match="DNS"):
        cfg(name="enp7s0", role="lan", ipv4="static", address="192.168.10.1/24", dns=["1.1.1.1"])


def test_off_forbids_parameters():
    with pytest.raises(ValueError, match="выключенного"):
        cfg(name="enp5s0", role="off", ipv4="dhcp")
    with pytest.raises(ValueError, match="выключенного"):
        cfg(name="enp5s0", role="off", mtu=9000)
    assert cfg(name="enp5s0", role="off").role == "off"


def test_mtu_range():
    with pytest.raises(ValueError, match="MTU"):
        cfg(name="enp5s0", role="wan", ipv4="dhcp", mtu=10)
    assert cfg(name="enp5s0", role="wan", ipv4="dhcp", mtu=9000).mtu == 9000


def test_bad_name_and_role():
    with pytest.raises(ValueError, match="имя"):
        cfg(name="eth 0", role="wan", ipv4="dhcp")
    with pytest.raises(ValueError, match="lo"):
        cfg(name="lo", role="wan", ipv4="dhcp")
    with pytest.raises(ValueError, match="Роль"):
        cfg(name="enp5s0", role="wifi")


def test_ipv4_required_for_wan_and_lan():
    with pytest.raises(ValueError, match="IPv4"):
        cfg(name="enp5s0", role="wan")


# ---------- генератор ----------

def test_render_wan_dhcp():
    text = render_network(cfg(name="enp5s0", role="wan", ipv4="dhcp"))
    assert "[Match]" in text and "Name=enp5s0" in text
    assert "DHCP=ipv4" in text
    assert "ClientIdentifier=mac" in text
    assert "Gateway=" not in text


def test_render_wan_static():
    text = render_network(
        cfg(
            name="enp5s0",
            role="wan",
            ipv4="static",
            address="192.168.1.2/24",
            gateway="192.168.1.1",
            dns=["1.1.1.1", "8.8.8.8"],
            mtu=1500,
        )
    )
    assert "Address=192.168.1.2/24" in text
    assert "Gateway=192.168.1.1" in text
    assert "DNS=1.1.1.1" in text and "DNS=8.8.8.8" in text
    assert "MTUSize=1500" in text
    assert "DHCP=" not in text


def test_render_lan_static_has_no_gateway():
    text = render_network(cfg(name="enp7s0", role="lan", ipv4="static", address="192.168.10.1/24"))
    assert "Address=192.168.10.1/24" in text
    assert "Gateway=" not in text
    assert "DNS=" not in text


def test_mac_validation():
    item = cfg(name="enp5s0", role="wan", ipv4="dhcp", mac="AA:BB:CC:DD:EE:FF")
    assert item.mac == "aa:bb:cc:dd:ee:ff"
    assert cfg(name="enp5s0", role="wan", ipv4="dhcp", mac="  ").mac is None
    with pytest.raises(ValueError, match="только для WAN"):
        cfg(
            name="enp7s0",
            role="lan",
            ipv4="static",
            address="192.168.10.1/24",
            mac="aa:bb:cc:dd:ee:ff",
        )
    with pytest.raises(ValueError, match="Некорректный MAC"):
        cfg(name="enp5s0", role="wan", ipv4="dhcp", mac="aa:bb:cc:dd:ee")
    with pytest.raises(ValueError, match="никакие параметры"):
        cfg(name="enp5s0", role="off", mac="aa:bb:cc:dd:ee:ff")


def test_pppoe_validation():
    item = cfg(name="enp5s0", role="wan", ipv4="pppoe", pppoe_username=" user@isp ")
    assert item.pppoe_username == "user@isp"
    assert item.pppoe_password is None
    with pytest.raises(ValueError, match="логин PPPoE"):
        cfg(name="enp5s0", role="wan", ipv4="pppoe")
    with pytest.raises(ValueError, match="только для WAN"):
        cfg(name="enp7s0", role="lan", ipv4="pppoe", pppoe_username="u")
    with pytest.raises(ValueError, match="адрес и шлюз"):
        cfg(name="enp5s0", role="wan", ipv4="pppoe", pppoe_username="u", gateway="192.168.1.1")
    with pytest.raises(ValueError, match="кавычек"):
        cfg(name="enp5s0", role="wan", ipv4="pppoe", pppoe_username="u", pppoe_password='pa"ss')
    with pytest.raises(ValueError, match="никакие параметры"):
        cfg(name="enp5s0", role="off", pppoe_username="u")


def test_render_mac_link_section():
    text = render_network(cfg(name="enp5s0", role="wan", ipv4="dhcp", mac="AA:BB:CC:DD:EE:FF"))
    assert "[Link]" in text and "MACAddress=aa:bb:cc:dd:ee:ff" in text
    assert text.index("[Link]") < text.index("[Network]")


def test_render_pppoe_staging(tmp_path: Path):
    staging = tmp_path / "staging"
    state = {
        "items": {
            "enp5s0": cfg(
                name="enp5s0",
                role="wan",
                ipv4="pppoe",
                pppoe_username="user@isp",
                pppoe_password="pa55",
                dns=["1.1.1.1"],
                mtu=1492,
            )
        },
        "segments": [
            SegmentConfig(
                id="home",
                name="Домашняя",
                interfaces=["enp7s0"],
                address="192.168.10.1/24",
                dhcp=DhcpSettings(enabled=False),
            )
        ],
        "routes": [],
        "wan": WanConfig(policies={"enp5s0": WanPolicy(priority=1)}),
    }
    state["items"]["enp7s0"] = cfg(
        name="enp7s0", role="lan", ipv4="static", address="192.168.10.1/24"
    )
    compose_staging(staging, state, mgmt=MGMT)

    port = (staging / "altrouter-enp5s0.network").read_text(encoding="utf-8")
    assert "DHCP=" not in port and "Address=" not in port
    assert "MTUSize=" not in port and "RouteMetric" not in port

    peers = (staging / "altrouter-ppp-enp5s0.peers").read_text(encoding="utf-8")
    assert "plugin rp-pppoe.so" in peers and "enp5s0" in peers
    assert "ifname ppp-enp5s0" in peers
    assert 'user "user@isp"' in peers and 'password "pa55"' in peers
    assert "defaultroute" in peers and "nodetach" in peers and "mtu 1492" in peers

    unit = (staging / "altrouter-ppp-enp5s0.service").read_text(encoding="utf-8")
    assert "ExecStart=/usr/sbin/pppd call altrouter-ppp-enp5s0" in unit

    nft = (staging / "nftables.conf").read_text(encoding="utf-8")
    assert 'oifname "ppp-enp5s0" masquerade' in nft
    assert (staging / "dnsmasq.conf").read_text(encoding="utf-8").find("server=1.1.1.1") >= 0


def test_file_name_prefix():
    assert network_file_name("enp5s0") == "altrouter-enp5s0.network"


def test_compose_staging_skips_off_and_cleans(tmp_path: Path):
    staging = tmp_path / "staging"

    def state(items):
        return {"items": dict(items), "segments": [], "routes": [], "wan": WanConfig()}

    compose_staging(
        staging,
        state(
            {
                "enp5s0": cfg(name="enp5s0", role="wan", ipv4="dhcp"),
                "enp6s0": cfg(name="enp6s0", role="off"),
            }
        ),
        mgmt=MGMT,
    )
    assert (staging / "altrouter-enp5s0.network").exists()
    assert not (staging / "altrouter-enp6s0.network").exists()
    assert (staging / "dnsmasq.conf").exists()
    assert (staging / "nftables.conf").exists()

    compose_staging(
        staging, state({"enp6s0": cfg(name="enp6s0", role="wan", ipv4="dhcp")}), mgmt=MGMT
    )
    assert not (staging / "altrouter-enp5s0.network").exists()
    assert (staging / "altrouter-enp6s0.network").exists()


def test_wan_policy_weight_validation():
    assert WanPolicy(priority=1, weight="").weight == 1
    assert WanPolicy(priority=1, weight=50).weight == 50
    with pytest.raises(ValueError, match="Вес"):
        WanPolicy(priority=1, weight=0)
    with pytest.raises(ValueError, match="Режим WAN"):
        WanConfig(mode="magic")
    assert WanConfig(mode=None).mode == "failover"


def _balance_state() -> dict:
    seg = SegmentConfig(
        id="home", name="Домашняя", interfaces=["enp7s0"], address="192.168.10.1/24"
    )
    return {
        "items": {
            "enp5s0": cfg(name="enp5s0", role="wan", ipv4="dhcp"),
            "enp6s0": cfg(
                name="enp6s0",
                role="wan",
                ipv4="static",
                address="10.20.0.2/24",
                gateway="10.20.0.1",
            ),
            "enp7s0": cfg(name="enp7s0", role="lan", ipv4="static", address="192.168.10.1/24"),
        },
        "segments": [seg],
        "routes": [],
        "wan": WanConfig(
            mode="balance",
            policies={"enp5s0": WanPolicy(priority=1, weight=3), "enp6s0": WanPolicy(weight=1)},
        ),
    }


def test_compose_balance_mode(tmp_path: Path):
    staging = tmp_path / "staging"
    compose_staging(staging, _balance_state(), mgmt=MGMT)

    wan1 = (staging / "altrouter-enp5s0.network").read_text(encoding="utf-8")
    assert "RouteMetric=100" in wan1 and "RouteTable" not in wan1
    assert "Gateway=_dhcp4" in wan1 and "Table=65536" in wan1
    assert "SuppressPrefixLength=0" in wan1 and "Priority=21999" in wan1
    assert "FirewallMark=65536" in wan1 and "Priority=22001" in wan1

    wan2 = (staging / "altrouter-enp6s0.network").read_text(encoding="utf-8")
    assert "Table=65537" in wan2 and "FirewallMark=65537" in wan2 and "Priority=22002" in wan2
    assert "SuppressPrefixLength" not in wan2

    nft = (staging / "nftables.conf").read_text(encoding="utf-8")
    assert "table ip altrouter_balance {" in nft
    assert "hook prerouting priority mangle" in nft
    assert "jhash ip saddr . ip daddr . th sport . th dport mod 4 lt 3 ct mark set 65536" in nft
    assert "meta l4proto != { tcp, udp } ct mark set 65537" in nft
    assert "lt 4" not in nft
    assert 'iifname "arbr-home"' in nft
    assert "meta mark set ct mark" in nft


def test_compose_failover_has_no_balance(tmp_path: Path):
    state = _balance_state()
    state["wan"] = WanConfig(
        policies={"enp5s0": WanPolicy(priority=1, weight=3), "enp6s0": WanPolicy(weight=1)}
    )
    staging = tmp_path / "staging"
    compose_staging(staging, state, mgmt=MGMT)
    wan1 = (staging / "altrouter-enp5s0.network").read_text(encoding="utf-8")
    assert "RouteMetric=100" in wan1 and "FirewallMark" not in wan1
    assert "altrouter_balance" not in (staging / "nftables.conf").read_text(encoding="utf-8")


def test_validate_balance_restrictions():
    state = _balance_state()
    validate_state(state, mgmt=MGMT)

    single = _balance_state()
    del single["items"]["enp6s0"]
    single["wan"].policies.pop("enp6s0")
    with pytest.raises(NetworkError, match="Балансировка"):
        validate_state(single, mgmt=MGMT)

    pppoe = _balance_state()
    pppoe["items"]["enp6s0"] = cfg(
        name="enp6s0", role="wan", ipv4="pppoe", pppoe_username="u"
    )
    with pytest.raises(NetworkError, match="PPPoE"):
        validate_state(pppoe, mgmt=MGMT)


# ---------- менеджер ----------

def make_manager(tmp_path: Path, calls: list, timeout: float = 3600) -> InterfaceManager:
    def applier():
        calls.append(time.time())

    return InterfaceManager(tmp_path, applier=applier, mgmt_iface=MGMT, confirm_timeout=timeout)


def journal_actions(mgr: InterfaceManager) -> list[str]:
    if not mgr.journal_path.exists():
        return []
    lines = mgr.journal_path.read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line)["action"] for line in lines]


def test_snapshot_initially_empty(tmp_path: Path):
    mgr = make_manager(tmp_path, [])
    snapshot = mgr.snapshot()
    assert snapshot["items"] == {}
    assert snapshot["management"] == MGMT
    assert snapshot["pending"] is None


def test_apply_rejects_management_iface(tmp_path: Path):
    mgr = make_manager(tmp_path, [])
    with pytest.raises(NetworkError, match="управляющий"):
        mgr.apply({MGMT: cfg(name=MGMT, role="wan", ipv4="dhcp")}, "admin")


def test_apply_creates_pending_and_staging(tmp_path: Path):
    calls: list = []
    mgr = make_manager(tmp_path, calls)
    pending = mgr.apply(
        {"enp5s0": cfg(name="enp5s0", role="wan", ipv4="dhcp", dns=["1.1.1.1"])}, "admin"
    )
    assert pending is not None and pending["username"] == "admin"
    assert (mgr.staging_dir / "altrouter-enp5s0.network").exists()
    assert mgr.pending_path.exists()
    assert len(calls) == 1
    assert journal_actions(mgr)[-1] == "applied"
    assert mgr.snapshot()["pending"] is not None


def test_confirm_timer_scheduled_from_event_loop(tmp_path: Path):
    calls: list = []
    mgr = make_manager(tmp_path, calls, timeout=3600)
    status = mgr.apply({"enp5s0": cfg(name="enp5s0", role="wan", ipv4="dhcp")}, "admin")
    assert mgr._timer_task is None

    async def driver():
        mgr.schedule_confirm_timer(status)
        await asyncio.sleep(0)
        assert mgr._timer_task is not None

    asyncio.run(driver())
    mgr._timer_task.cancel()


def test_second_apply_while_pending_rejected(tmp_path: Path):
    mgr = make_manager(tmp_path, [])
    mgr.apply({"enp5s0": cfg(name="enp5s0", role="wan", ipv4="dhcp")}, "admin")
    with pytest.raises(NetworkError, match="подтвердите"):
        mgr.apply({"enp6s0": cfg(name="enp6s0", role="wan", ipv4="dhcp")}, "admin")


def test_confirm_persists_state(tmp_path: Path):
    calls: list = []
    mgr = make_manager(tmp_path, calls)
    mgr.apply({"enp5s0": cfg(name="enp5s0", role="wan", ipv4="dhcp")}, "admin")
    result = mgr.confirm()
    assert result["ok"] is True
    assert len(calls) == 1  # confirm не вызывает applier повторно
    assert not mgr.pending_path.exists()
    items = mgr.snapshot()["items"]
    assert items["enp5s0"]["role"] == "wan"
    assert journal_actions(mgr) == ["applied", "committed"]
    with pytest.raises(NetworkError):
        mgr.confirm()


def test_rollback_restores_previous_staging(tmp_path: Path):
    calls: list = []
    mgr = make_manager(tmp_path, calls)
    first = {"enp5s0": cfg(name="enp5s0", role="wan", ipv4="dhcp")}
    mgr.apply(first, "admin")
    mgr.confirm()

    second = {"enp5s0": cfg(name="enp5s0", role="off")}
    mgr.apply(second, "admin")
    assert not (mgr.staging_dir / "altrouter-enp5s0.network").exists()
    mgr.rollback("тест")

    assert (mgr.staging_dir / "altrouter-enp5s0.network").exists()
    assert not mgr.pending_path.exists()
    assert mgr.snapshot()["items"]["enp5s0"]["role"] == "wan"
    assert len(calls) == 3  # apply, apply, rollback
    assert journal_actions(mgr) == ["applied", "committed", "applied", "rolled_back"]


def test_expired_pending_rolls_back_lazily(tmp_path: Path):
    calls: list = []
    mgr = make_manager(tmp_path, calls, timeout=0.05)
    mgr.apply({"enp5s0": cfg(name="enp5s0", role="wan", ipv4="dhcp")}, "admin")
    time.sleep(0.15)
    assert mgr.snapshot()["pending"] is None
    assert mgr.snapshot()["items"] == {}
    assert journal_actions(mgr) == ["applied", "rolled_back"]
    assert len(calls) == 2


def test_restart_recovers_pending(tmp_path: Path):
    calls: list = []
    mgr = make_manager(tmp_path, calls)
    mgr.apply({"enp5s0": cfg(name="enp5s0", role="wan", ipv4="dhcp")}, "admin")

    fresh = make_manager(tmp_path, calls)
    assert not fresh.pending_path.exists()
    assert fresh.snapshot()["items"] == {}
    assert journal_actions(fresh)[-1] == "rolled_back"
    assert len(calls) == 2


def test_apply_failure_restores_staging(tmp_path: Path):
    calls: list = []

    def flaky_applier():
        calls.append(1)
        if len(calls) == 2:
            raise ApplyError("networkctl недоступен")

    mgr = InterfaceManager(
        tmp_path, applier=flaky_applier, mgmt_iface=MGMT, confirm_timeout=3600
    )
    mgr.apply({"enp5s0": cfg(name="enp5s0", role="wan", ipv4="dhcp")}, "admin")
    mgr.confirm()
    with pytest.raises(ApplyError):
        mgr.apply({"enp6s0": cfg(name="enp6s0", role="wan", ipv4="dhcp")}, "admin")
    # staging вернулся к состоянию до неудачной транзакции
    assert (mgr.staging_dir / "altrouter-enp5s0.network").exists()
    assert not (mgr.staging_dir / "altrouter-enp6s0.network").exists()
    assert not mgr.pending_path.exists()
    # сбой применения зафиксирован в журнале с текстом ошибки
    lines = mgr.journal_path.read_text(encoding="utf-8").strip().splitlines()
    failed = json.loads(lines[-1])
    assert failed["action"] == "apply_failed"
    assert "networkctl недоступен" in failed["error"]


# ---------- этап 3: секции состояния ----------

LAN_ITEM = cfg(name="enp7s0", role="lan", ipv4="static", address="192.168.30.1/24")


def segment(interfaces=("enp7s0",), seg_id="home") -> SegmentConfig:
    return SegmentConfig(
        id=seg_id,
        name="Домашняя",
        interfaces=list(interfaces),
        address="192.168.10.1/24",
        dhcp=DhcpSettings(enabled=True, pool_start="192.168.10.50", pool_end="192.168.10.150"),
    )


def test_apply_sections_segments_full_cycle(tmp_path: Path):
    calls: list = []
    mgr = make_manager(tmp_path, calls)
    mgr.apply({"enp5s0": cfg(name="enp5s0", role="wan", ipv4="dhcp"), "enp7s0": LAN_ITEM}, "admin")
    mgr.confirm()

    pending = mgr.apply_sections({"segments": [segment()]}, "admin")
    assert pending["username"] == "admin"
    assert pending["sections"]["segments"][0]["id"] == "home"
    assert (mgr.staging_dir / "altrouter-arbr-home.netdev").exists()
    assert "dhcp-range=set:home" in (mgr.staging_dir / "dnsmasq.conf").read_text(encoding="utf-8")
    # порт сегмента стал ведомым моста
    assert "Bridge=arbr-home" in (mgr.staging_dir / "altrouter-enp7s0.network").read_text(
        encoding="utf-8"
    )
    # коммитнутые интерфейсы не изменились
    assert mgr.snapshot()["items"]["enp7s0"]["address"] == "192.168.30.1/24"

    mgr.confirm()
    snapshot = mgr.snapshot()
    assert snapshot["segments"][0]["id"] == "home"
    assert snapshot["pending"] is None
    assert len(calls) == 2
    assert journal_actions(mgr)[-1] == "committed"


def test_apply_sections_rolls_back_segments(tmp_path: Path):
    calls: list = []
    mgr = make_manager(tmp_path, calls)
    mgr.apply({"enp5s0": cfg(name="enp5s0", role="wan", ipv4="dhcp"), "enp7s0": LAN_ITEM}, "admin")
    mgr.confirm()
    mgr.apply_sections({"segments": [segment()]}, "admin")
    mgr.rollback("тест")

    assert not (mgr.staging_dir / "altrouter-arbr-home.netdev").exists()
    assert mgr.snapshot()["segments"] == []
    assert "Address=192.168.30.1/24" in (mgr.staging_dir / "altrouter-enp7s0.network").read_text(
        encoding="utf-8"
    )
    assert journal_actions(mgr)[-1] == "rolled_back"


def test_apply_sections_wan_and_routes(tmp_path: Path):
    calls: list = []
    mgr = make_manager(tmp_path, calls)
    mgr.apply({"enp5s0": cfg(name="enp5s0", role="wan", ipv4="dhcp"), "enp7s0": LAN_ITEM}, "admin")
    mgr.confirm()

    mgr.apply_sections(
        {
            "wan": WanConfig(policies={"enp5s0": WanPolicy(priority=2)}),
            "routes": [StaticRoute(dest="10.5.0.0/16", gateway="192.168.30.1")],
        },
        "admin",
    )
    wan_text = (mgr.staging_dir / "altrouter-enp5s0.network").read_text(encoding="utf-8")
    assert "RouteMetric=200" in wan_text
    lan_text = (mgr.staging_dir / "altrouter-enp7s0.network").read_text(encoding="utf-8")
    assert "Destination=10.5.0.0/16" in lan_text
    mgr.confirm()
    snapshot = mgr.snapshot()
    assert snapshot["wan"]["policies"]["enp5s0"]["priority"] == 2
    assert snapshot["routes"][0]["dest"] == "10.5.0.0/16"


def test_legacy_state_file_migrates(tmp_path: Path):
    legacy = {
        "items": {"enp5s0": cfg(name="enp5s0", role="wan", ipv4="dhcp").model_dump()}
    }
    network_dir = tmp_path / "network"
    network_dir.mkdir()
    (network_dir / "network.json").write_text(json.dumps(legacy), encoding="utf-8")

    mgr = make_manager(tmp_path, [])
    snapshot = mgr.snapshot()
    assert snapshot["items"]["enp5s0"]["role"] == "wan"
    assert snapshot["segments"] == []
    assert snapshot["routes"] == []
    assert snapshot["wan"] == {"policies": {}, "mode": "failover"}


def test_apply_sections_validates_against_committed(tmp_path: Path):
    mgr = make_manager(tmp_path, [])
    mgr.apply({"enp5s0": cfg(name="enp5s0", role="wan", ipv4="dhcp"), "enp7s0": LAN_ITEM}, "admin")
    mgr.confirm()
    with pytest.raises(NetworkError, match="не назначен LAN-ролью"):
        mgr.apply_sections({"segments": [segment(interfaces=("enp5s0",))]}, "admin")
    assert not mgr.pending_path.exists()
