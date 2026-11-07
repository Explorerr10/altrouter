"""Этап 4: модели правил, зон и DNAT, рендер nftables/dnsmasq, кросс-валидация."""

import pytest

from app.network.composer import (
    bridge_name,
    compose_staging,
    render_dnsmasq,
    render_nftables,
    resolve_forward_egress,
    validate_state,
    zone_interfaces,
)
from app.network.errors import NetworkError
from app.network.firewall import DnsRecord, FirewallRule, PortForward
from app.network.models import InterfaceConfig
from app.network.segments import DhcpSettings, SegmentConfig, WanConfig, WanPolicy

MGMT = "enp9s0f0"


# ---------- модели: правила файрвола ----------

def test_rule_defaults_and_normalization():
    rule = FirewallRule(zone=" WAN ", action=" DROP ")
    assert rule.direction == "forward"
    assert rule.zone == "wan"
    assert rule.proto == "any"
    assert rule.action == "drop"
    assert rule.src_ip is None and rule.src_port is None


def test_rule_parses_addresses_and_ports():
    rule = FirewallRule(
        proto="tcp",
        src_ip="192.168.10.0/24",
        src_port="8000-9000",
        dst_ip="192.168.20.7",
        dst_port="443",
    )
    assert rule.src_ip == "192.168.10.0/24"
    assert rule.src_port == "8000-9000"
    assert rule.dst_ip == "192.168.20.7"
    assert rule.dst_port == "443"


def test_rule_rejects_unknown_direction_proto_action():
    with pytest.raises(ValueError, match="Направление"):
        FirewallRule(direction="both")
    with pytest.raises(ValueError, match="Протокол"):
        FirewallRule(proto="gre")
    with pytest.raises(ValueError, match="Действие"):
        FirewallRule(action="reject")
    with pytest.raises(ValueError, match="зона"):
        FirewallRule(zone="Not Valid!")


def test_rule_rejects_ports_with_any_proto():
    with pytest.raises(ValueError, match="Порты"):
        FirewallRule(proto="any", dst_port="80")


def test_rule_port_spec_validation():
    with pytest.raises(ValueError, match="Некорректный"):
        FirewallRule(dst_port="abc")
    with pytest.raises(ValueError, match="от 1 до 65535"):
        FirewallRule(dst_port="0")
    with pytest.raises(ValueError, match="меньше конца"):
        FirewallRule(dst_port="9000-8000")


# ---------- модели: переадресация портов ----------

def forward(**kwargs) -> PortForward:
    base = {"proto": "tcp", "port": "8080", "to_ip": "192.168.10.50"}
    base.update(kwargs)
    return PortForward(**base)


def test_forward_defaults():
    fw = forward()
    assert fw.wan is None
    assert fw.to_port is None
    assert fw.comment is None


def test_forward_rejects_bad_proto_and_port():
    with pytest.raises(ValueError, match="Протокол"):
        forward(proto="icmp")
    with pytest.raises(ValueError, match="Некорректный"):
        forward(port="80-")
    with pytest.raises(ValueError, match="IPv4"):
        forward(to_ip="fe80::1")


def test_forward_to_port_range_size_must_match():
    fw = forward(port="8000-8010", to_port="9000-9010")
    assert fw.to_port == "9000-9010"
    with pytest.raises(ValueError, match="по размеру"):
        forward(port="8000-8010", to_port="9000")
    with pytest.raises(ValueError, match="по размеру"):
        forward(port="8080", to_port="9000-9010")


# ---------- модели: локальные DNS-имена ----------

def test_dns_record_normalizes():
    rec = DnsRecord(hostname="nas.local", ip=" 192.168.10.20 ", comment=" хранилище ")
    assert rec.hostname == "nas.local"
    assert rec.ip == "192.168.10.20"
    assert rec.comment == "хранилище"


def test_dns_record_rejects_bad_name_and_ip():
    with pytest.raises(ValueError, match="имя хоста"):
        DnsRecord(hostname="-bad-", ip="192.168.10.20")
    with pytest.raises(ValueError, match="IP"):
        DnsRecord(hostname="nas", ip="192.168.10.300")


# ---------- состояние и кросс-валидация ----------

def wan_iface(name="enp5s0") -> tuple[str, InterfaceConfig]:
    return name, InterfaceConfig(name=name, role="wan", ipv4="dhcp")


def lan_iface(name, address) -> tuple[str, InterfaceConfig]:
    return name, InterfaceConfig(name=name, role="lan", ipv4="static", address=address)


def segment(**kwargs) -> SegmentConfig:
    base = {
        "id": "home",
        "name": "Домашняя",
        "interfaces": ["enp7s0"],
        "address": "192.168.10.1/24",
        "dhcp": DhcpSettings(enabled=False),
        "reservations": [],
    }
    base.update(kwargs)
    return SegmentConfig(**base)


def make_state(rules=None, forwards=None, dns=None, segments=None, items=None) -> dict:
    return {
        "items": items
        if items is not None
        else dict([wan_iface(), lan_iface("enp7s0", "192.168.30.1/24")]),
        "segments": segments if segments is not None else [segment()],
        "routes": [],
        "wan": WanConfig(policies={}),
        "rules": rules or [],
        "forwards": forwards or [],
        "dns": dns or [],
    }


def test_zone_interfaces_resolution():
    items = dict([wan_iface("enp5s0"), wan_iface("enp6s0"), lan_iface("enp8s0", "192.168.40.1/24")])
    segs = [
        segment(),
        segment(id="iot", name="IoT", interfaces=["enp8s0"], address="192.168.9.1/24"),
    ]
    assert zone_interfaces("wan", items, segs) == ["enp5s0", "enp6s0"]
    assert zone_interfaces("lan", items, segs) == [
        bridge_name("home"),
        bridge_name("iot"),
    ]
    assert zone_interfaces("iot", items, segs) == [bridge_name("iot")]
    with pytest.raises(NetworkError, match="Неизвестная зона"):
        zone_interfaces("guest", items, segs)


def test_validate_rejects_unknown_zone():
    state = make_state(rules=[FirewallRule(zone="guest")])
    with pytest.raises(NetworkError, match="нет сегмента"):
        validate_state(state, mgmt=MGMT)


def test_validate_rejects_zone_without_interfaces():
    state = make_state(rules=[FirewallRule(direction="input", zone="wan", action="drop")])
    state["items"] = dict([lan_iface("enp7s0", "192.168.30.1/24")])
    with pytest.raises(NetworkError, match="нет интерфейсов"):
        validate_state(state, mgmt=MGMT)


def test_validate_rejects_forward_to_unknown_wan():
    state = make_state(forwards=[forward(wan="enp8s0")])
    with pytest.raises(NetworkError, match="не является WAN"):
        validate_state(state, mgmt=MGMT)


def test_validate_rejects_forward_without_any_wan():
    state = make_state(forwards=[forward()])
    state["items"] = dict([lan_iface("enp7s0", "192.168.30.1/24")])
    with pytest.raises(NetworkError, match="нет ни одного WAN"):
        validate_state(state, mgmt=MGMT)


def test_validate_rejects_forward_target_outside_subnets():
    state = make_state(forwards=[forward(to_ip="10.99.0.5")])
    with pytest.raises(NetworkError, match="не входит ни в одну известную подсеть"):
        validate_state(state, mgmt=MGMT)


def test_validate_rejects_duplicate_forward():
    state = make_state(forwards=[forward(), forward(comment="копия")])
    with pytest.raises(NetworkError, match="уже задана"):
        validate_state(state, mgmt=MGMT)


def test_validate_rejects_duplicate_and_foreign_dns_name():
    state = make_state(dns=[DnsRecord(hostname="nas", ip="192.168.10.20")])
    validate_state(state, mgmt=MGMT)
    state["dns"] = [
        DnsRecord(hostname="nas", ip="192.168.10.20"),
        DnsRecord(hostname="nas", ip="192.168.10.21"),
    ]
    with pytest.raises(NetworkError, match="дважды"):
        validate_state(state, mgmt=MGMT)
    state["dns"] = [DnsRecord(hostname="printer", ip="172.16.0.9")]
    with pytest.raises(NetworkError, match="не входит ни в одну"):
        validate_state(state, mgmt=MGMT)


def test_resolve_forward_egress_prefers_segment_bridge():
    fw = forward(to_ip="192.168.10.50")
    assert resolve_forward_egress(fw, make_state()["items"], make_state()["segments"]) == (
        bridge_name("home")
    )


# ---------- рендер nftables ----------

def nftables_text(**state_kwargs) -> str:
    return render_nftables(make_state(**state_kwargs), mgmt=MGMT)


def test_nftables_without_rules_keeps_base_policy():
    text = nftables_text()
    assert "table inet altrouter_filter {" in text
    assert 'iifname "enp9s0f0" accept comment "управляющий интерфейс"' in text
    assert "type nat hook prerouting priority dstnat; policy accept;" in text
    assert "dnat to" not in text


def test_nftables_input_rules_before_zone_accepts():
    text = nftables_text(
        rules=[
            FirewallRule(
                direction="input", zone="wan", proto="tcp", dst_port="22", action="allow",
                comment="ssh",
            ),
            FirewallRule(direction="input", zone="home", action="drop"),
        ]
    )
    mgmt_pos = text.index("управляющий интерфейс")
    ssh_pos = text.index('tcp dport 22 accept comment "правило 1 (ssh)"')
    drop_pos = text.index('iifname "arbr-home" drop')
    segment_accept_pos = text.index('iifname "arbr-home" accept comment "сегмент home"')
    assert mgmt_pos < ssh_pos < drop_pos < segment_accept_pos


def test_nftables_lan_zone_expands_to_all_lan_ifaces():
    items = dict(
        [
            wan_iface(),
            lan_iface("enp7s0", "192.168.30.1/24"),
            lan_iface("enp8s0", "192.168.40.1/24"),
        ]
    )
    text = nftables_text(
        items=items,
        rules=[
            FirewallRule(direction="input", zone="lan", proto="tcp", dst_port="80", action="drop")
        ],
    )
    assert 'iifname "arbr-home" tcp dport 80 drop' in text
    assert 'iifname "enp8s0" tcp dport 80 drop' in text


def test_nftables_forward_rules_and_dnat():
    items = dict([wan_iface("enp5s0"), wan_iface("enp6s0"), lan_iface("enp7s0", "192.168.30.1/24")])
    text = nftables_text(
        items=items,
        rules=[FirewallRule(zone="wan", proto="tcp", dst_port="25", action="drop")],
        forwards=[
            PortForward(
                wan=None, proto="tcp", port="8080", to_ip="192.168.10.50", to_port="80",
                comment="web",
            ),
            PortForward(wan="enp5s0", proto="udp", port="51820", to_ip="192.168.10.60"),
        ],
    )
    assert (
        'iifname "enp5s0" tcp dport 8080 dnat to 192.168.10.50:80 '
        'comment "DNAT tcp/8080 (web)"' in text
    )
    assert (
        'iifname "enp6s0" tcp dport 8080 dnat to 192.168.10.50:80' in text
    )
    assert 'iifname "enp5s0" udp dport 51820 dnat to 192.168.10.60' in text
    accept = 'iifname "enp5s0" oifname "arbr-home" ip daddr 192.168.10.50 tcp dport 80 accept'
    assert accept in text
    drop25_pos = text.index('tcp dport 25 drop comment "правило 1"')
    accept_pos = text.index(accept)
    base_seg_wan_pos = text.index("сегмент home -> WAN enp5s0")
    assert accept_pos < drop25_pos < base_seg_wan_pos


def test_nftables_dnat_range_forwarded_with_range():
    text = nftables_text(
        forwards=[PortForward(port="8000-8010", to_ip="192.168.10.50", to_port="9000-9010")]
    )
    assert "tcp dport 8000-8010 dnat to 192.168.10.50:9000-9010" in text
    assert "tcp dport 9000-9010 accept" in text


def test_nftables_forward_both_proto_emits_tcp_and_udp():
    text = nftables_text(
        forwards=[PortForward(proto="both", port="53", to_ip="192.168.10.70")]
    )
    assert 'tcp dport 53 dnat to 192.168.10.70 comment "DNAT both/53"' in text
    assert 'udp dport 53 dnat to 192.168.10.70 comment "DNAT both/53"' in text
    assert "udp dport 53 accept" in text


def test_nftables_hairpin_dnat_accept_and_masquerade():
    text = nftables_text(
        forwards=[PortForward(port="8080", to_ip="192.168.10.50", to_port="80")]
    )
    assert (
        'iifname { "arbr-home" } fib daddr type local tcp dport 8080 dnat to '
        '192.168.10.50:80 comment "DNAT hairpin DNAT tcp/8080"' in text
    )
    assert (
        'iifname { "arbr-home" } oifname "arbr-home" ip daddr 192.168.10.50 tcp dport 80 accept '
        'comment "DNAT hairpin DNAT tcp/8080"' in text
    )
    assert (
        'iifname "arbr-home" oifname "arbr-home" ip saddr 192.168.10.0/24 masquerade '
        'comment "hairpin сегмент home"' in text
    )


def test_nftables_hairpin_masquerades_cross_segment():
    home = segment(id="home", address="192.168.10.1/24")
    servers = segment(id="servers", address="192.168.0.1/24")
    text = nftables_text(segments=[home, servers])
    assert (
        'iifname "arbr-home" oifname { "arbr-servers" } ip saddr 192.168.10.0/24 masquerade '
        'comment "hairpin сегмент home -> другие сегменты"' in text
    )
    assert (
        'iifname "arbr-servers" oifname { "arbr-home" } ip saddr 192.168.0.0/24 masquerade '
        'comment "hairpin сегмент servers -> другие сегменты"' in text
    )


def test_nftables_hairpin_forward_accepts_cross_bridge():
    home = segment(id="home", address="192.168.10.1/24")
    servers = segment(id="servers", address="192.168.0.1/24")
    text = nftables_text(
        segments=[home, servers],
        forwards=[PortForward(port="80", to_ip="192.168.0.111", to_port="80")],
    )
    assert (
        'iifname { "arbr-home", "arbr-servers" } oifname "arbr-servers" '
        'ip daddr 192.168.0.111 tcp dport 80 accept '
        'comment "DNAT hairpin DNAT tcp/80"' in text
    )


def test_nftables_balance_skips_local_addresses():
    items = dict([wan_iface("enp5s0"), wan_iface("enp6s0"), lan_iface("enp7s0", "192.168.30.1/24")])
    state = make_state(items=items)
    state["wan"] = WanConfig(
        mode="balance",
        policies={"enp5s0": WanPolicy(priority=1), "enp6s0": WanPolicy(priority=1)},
    )
    text = render_nftables(state, mgmt=MGMT)
    assert (
        'iifname { "arbr-home" } fib daddr type local accept '
        'comment "hairpin: не балансировать локальные адреса"' in text
    )


def test_nftables_balance_marks_wan_ingress():
    items = dict([wan_iface("enp5s0"), wan_iface("enp6s0"), lan_iface("enp7s0", "192.168.30.1/24")])
    state = make_state(items=items)
    state["wan"] = WanConfig(
        mode="balance",
        policies={"enp5s0": WanPolicy(priority=1), "enp6s0": WanPolicy(priority=1)},
    )
    text = render_nftables(state, mgmt=MGMT)
    assert (
        'iifname "enp5s0" ct state new ct mark 0 ct mark set 65536 '
        'comment "симметрия ответов enp5s0"' in text
    )
    assert (
        'iifname "enp6s0" ct state new ct mark 0 ct mark set 65537 '
        'comment "симметрия ответов enp6s0"' in text
    )
    assert text.index("симметрия ответов enp6s0") < text.index("марка соединения -> маршрут")
    assert "type route hook output priority mangle; policy accept;" in text
    assert 'ct mark != 0 meta mark set ct mark comment "марка соединения -> маршрут: локальные ответы"' in text


# ---------- рендер dnsmasq и staging ----------

def test_dnsmasq_includes_host_records():
    text = render_dnsmasq(
        make_state(dns=[DnsRecord(hostname="nas", ip="192.168.10.20", comment="хранилище")])
    )
    assert "host-record=nas,192.168.10.20 # хранилище" in text


def test_dnsmasq_without_records_has_no_host_records():
    assert "host-record" not in render_dnsmasq(make_state())


def test_compose_staging_writes_nftables_and_dnsmasq(tmp_path):
    staging = tmp_path / "staging"
    compose_staging(
        staging,
        make_state(
            rules=[FirewallRule(zone="wan", action="drop", comment="гость")],
            forwards=[forward()],
            dns=[DnsRecord(hostname="nas", ip="192.168.10.20")],
        ),
        mgmt=MGMT,
    )
    nft = (staging / "nftables.conf").read_text(encoding="utf-8")
    dns_conf = (staging / "dnsmasq.conf").read_text(encoding="utf-8")
    assert 'dnat to 192.168.10.50 comment "DNAT tcp/8080"' in nft
    assert 'comment "правило 1 (гость)"' in nft
    assert "host-record=nas,192.168.10.20" in dns_conf
