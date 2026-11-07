"""Композиция полной конфигурации роутера: networkd (порты/мосты/маршруты), dnsmasq, nftables."""

import ipaddress
from pathlib import Path

from .errors import NetworkError
from .firewall import DnsRecord, FirewallRule, PortForward
from .generator import (
    HEADER,
    MANAGED_PREFIX,
    link_lines,
    network_file_name,
    render_network,
)
from .models import InterfaceConfig
from .segments import SegmentConfig, StaticRoute, WanConfig
from .wireguard import WireguardInterface
from .wireguard import iface_name as wg_iface_name

BRIDGE_PREFIX = "arbr-"
DNSMASQ_FILE = "dnsmasq.conf"
NFTABLES_FILE = "nftables.conf"
STAGING_SUFFIXES = (".network", ".netdev", ".peers", ".service")
BALANCE_BASE = 65536  # таблицы/метки балансировки, выше занятого WireGuard (listen_port)


def bridge_name(segment_id: str) -> str:
    return f"{BRIDGE_PREFIX}{segment_id}"


def ppp_iface(cfg: InterfaceConfig) -> str:
    """Интерфейс, через который реально идёт трафик WAN (ppp-устройство при PPPoE)."""
    return f"ppp-{cfg.name}" if cfg.ipv4 == "pppoe" else cfg.name


def segment_of_port(segments: list[SegmentConfig], port: str) -> SegmentConfig | None:
    for seg in segments:
        if port in seg.interfaces:
            return seg
    return None


def _iface_networks(
    items: dict[str, InterfaceConfig], segments: list[SegmentConfig]
) -> list[tuple[str, ipaddress.IPv4Network]]:
    """L3-точки конфигурации: (имя интерфейса, подсеть).

    Адрес LAN-порта, входящего в сегмент, живёт на мосту сегмента.
    """
    nets: list[tuple[str, ipaddress.IPv4Network]] = []
    for name, cfg in items.items():
        if cfg.role != "off" and cfg.address and segment_of_port(segments, name) is None:
            nets.append((name, ipaddress.ip_interface(cfg.address).network))
    for seg in segments:
        nets.append((bridge_name(seg.id), ipaddress.ip_interface(seg.address).network))
    return nets


def resolve_route_egress(
    route: StaticRoute, items: dict[str, InterfaceConfig], segments: list[SegmentConfig]
) -> str:
    """Определяет интерфейс, через который доступен шлюз маршрута."""
    gateway = ipaddress.ip_address(route.gateway)
    matches = [iface for iface, net in _iface_networks(items, segments) if gateway in net]
    if not matches:
        raise NetworkError(
            f"Маршрут {route.dest}: шлюз {route.gateway} не входит ни в одну известную подсеть"
        )
    if route.iface and route.iface not in matches:
        raise NetworkError(
            f"Маршрут {route.dest}: шлюз {route.gateway} достижим через {', '.join(matches)}, "
            f"а не через {route.iface}"
        )
    return route.iface or matches[0]


def resolve_forward_egress(
    forward: PortForward, items: dict[str, InterfaceConfig], segments: list[SegmentConfig]
) -> str:
    """Определяет интерфейс, в подсеть которого адресован DNAT."""
    addr = ipaddress.ip_address(forward.to_ip)
    matches = [iface for iface, net in _iface_networks(items, segments) if addr in net]
    if not matches:
        raise NetworkError(
            f"Переадресация порта {forward.port}: адрес {forward.to_ip} "
            "не входит ни в одну известную подсеть"
        )
    return matches[0]


def zone_interfaces(
    zone: str, items: dict[str, InterfaceConfig], segments: list[SegmentConfig]
) -> list[str]:
    """Интерфейсы зоны: wan — все WAN, lan — мосты и LAN-порты без сегмента, иначе сегмент."""
    if zone == "wan":
        return sorted(ppp_iface(cfg) for cfg in items.values() if cfg.role == "wan")
    if zone == "lan":
        bridges = [bridge_name(seg.id) for seg in sorted(segments, key=lambda s: s.id)]
        return bridges + sorted(
            name
            for name, cfg in items.items()
            if cfg.role == "lan" and segment_of_port(segments, name) is None
        )
    for seg in segments:
        if seg.id == zone:
            return [bridge_name(seg.id)]
    raise NetworkError(f"Неизвестная зона «{zone}»")


def resolve_wg_devices(
    wg: WireguardInterface, items: dict[str, InterfaceConfig], segments: list[SegmentConfig]
) -> list[tuple[str, str]]:
    """Пары (адрес устройства, подсеть, в которой оно живёт) для policy routing."""
    nets = _iface_networks(items, segments)
    pairs: list[tuple[str, str]] = []
    for device in wg.devices:
        addr = ipaddress.ip_address(device.split("/")[0])
        matches = [str(net) for _, net in nets if addr in net]
        if not matches:
            raise NetworkError(
                f"Туннель «{wg.name}»: адрес {addr} не входит ни в одну известную подсеть"
            )
        pairs.append((device, matches[0]))
    return pairs


def validate_wireguard(
    wireguard: list[WireguardInterface],
    items: dict[str, InterfaceConfig],
    segments: list[SegmentConfig],
) -> None:
    """Кросс-валидация туннелей: уникальность портов, подсетей, адреса устройств."""
    known = _iface_networks(items, segments)
    seen_ports: set[int] = set()
    seen_nets: list[tuple[str, ipaddress.IPv4Network]] = list(known)
    for wg in wireguard:
        if wg.listen_port in seen_ports:
            raise NetworkError(
                f"Туннели «{wg.name}» и другой туннель используют порт {wg.listen_port} дважды"
            )
        seen_ports.add(wg.listen_port)
        for _other, net in seen_nets:
            if wg.network.overlaps(net):
                raise NetworkError(
                    f"Подсеть туннеля «{wg.name}» ({wg.network}) пересекается с {net}"
                )
        seen_nets.append((wg_iface_name(wg.id), wg.network))
        if wg.route_mode == "devices":
            resolve_wg_devices(wg, items, segments)


def validate_state(state: dict, mgmt: str) -> None:
    """Перекрёстная валидация полного состояния (после поэлементной валидации Pydantic)."""
    items: dict[str, InterfaceConfig] = state["items"]
    segments: list[SegmentConfig] = state["segments"]
    routes: list[StaticRoute] = state["routes"]
    wan: WanConfig = state["wan"]
    rules: list[FirewallRule] = state.get("rules") or []
    forwards: list[PortForward] = state.get("forwards") or []
    dns_records: list[DnsRecord] = state.get("dns") or []

    for name, cfg in items.items():
        if name == mgmt:
            raise NetworkError(f"Интерфейс {name} — управляющий, его изменение запрещено")
        if cfg.name != name:
            raise NetworkError(f"Ключ {name!r} не совпадает с именем интерфейса {cfg.name!r}")

    lan_ports = {name for name, cfg in items.items() if cfg.role == "lan"}
    wan_ports = {name for name, cfg in items.items() if cfg.role == "wan"}

    ids: set[str] = set()
    claimed: dict[str, str] = {}
    for seg in segments:
        if seg.id in ids:
            raise NetworkError(f"Сегмент с идентификатором {seg.id!r} уже есть")
        ids.add(seg.id)
        for port in seg.interfaces:
            if port not in lan_ports:
                raise NetworkError(
                    f"Сегмент «{seg.name}»: порт {port} не назначен LAN-ролью "
                    "(роль меняется в разделе «Интернет»)"
                )
            if port in claimed:
                raise NetworkError(
                    f"Порт {port} входит в несколько сегментов: «{claimed[port]}» и «{seg.name}»"
                )
            claimed[port] = seg.name

    seen: list[tuple[str, ipaddress.IPv4Network]] = []
    for iface, net in _iface_networks(items, segments):
        for other_iface, other_net in seen:
            if net.overlaps(other_net):
                raise NetworkError(
                    f"Подсети {iface} ({net}) и {other_iface} ({other_net}) пересекаются"
                )
        seen.append((iface, net))

    for route in routes:
        resolve_route_egress(route, items, segments)

    seg_ids = {seg.id for seg in segments}
    for index, rule in enumerate(rules, start=1):
        label = rule.comment or f"№{index}"
        if rule.zone not in seg_ids and rule.zone not in ("wan", "lan"):
            raise NetworkError(
                f"Правило «{label}»: нет сегмента с идентификатором «{rule.zone}»"
            )
        if not zone_interfaces(rule.zone, items, segments):
            raise NetworkError(
                f"Правило «{label}»: в зоне «{rule.zone}» нет интерфейсов "
                "(проверьте роли портов и сегменты)"
            )

    wan_names = sorted(wan_ports)
    seen_forwards: set[tuple[str | None, str, str]] = set()
    for fw in forwards:
        label = f"{fw.proto}/{fw.port}"
        if fw.wan and fw.wan not in wan_ports:
            raise NetworkError(
                f"Переадресация порта {label}: интерфейс {fw.wan} не является WAN-подключением"
            )
        if not fw.wan and not wan_names:
            raise NetworkError(
                f"Переадресация порта {label}: нет ни одного WAN-подключения — "
                "сначала настройте WAN в разделе «Интернет»"
            )
        resolve_forward_egress(fw, items, segments)
        key = (fw.wan, fw.proto, fw.port)
        if key in seen_forwards:
            target = fw.wan or "все WAN"
            raise NetworkError(f"Переадресация порта {label} на {target} уже задана")
        seen_forwards.add(key)

    known_nets = [net for _, net in _iface_networks(items, segments)]
    seen_names: set[str] = set()
    for rec in dns_records:
        if rec.hostname in seen_names:
            raise NetworkError(f"Локальное имя {rec.hostname} встречается дважды")
        seen_names.add(rec.hostname)
        addr = ipaddress.ip_address(rec.ip)
        if not any(addr in net for net in known_nets):
            raise NetworkError(
                f"Локальное имя {rec.hostname}: адрес {rec.ip} "
                "не входит ни в одну известную подсеть"
            )

    for iface in wan.policies:
        if iface not in wan_ports:
            raise NetworkError(
                f"Политика относится к интерфейсу {iface}, который не является WAN-подключением"
            )

    if wan.mode == "balance":
        pppoe = sorted(n for n, c in items.items() if c.role == "wan" and c.ipv4 == "pppoe")
        if pppoe:
            raise NetworkError(
                f"Балансировка не поддерживает PPPoE-подключения: {', '.join(pppoe)}"
            )
        if len(wan_ports) < 2:
            raise NetworkError("Балансировка требует не меньше двух WAN-подключений")

    validate_wireguard(state.get("wireguard") or [], items, segments)


# ---------- рендер networkd ----------


def _route_sections(routes: list[StaticRoute]) -> list[str]:
    lines: list[str] = []
    for route in routes:
        lines += ["", "[Route]", f"Destination={route.dest}", f"Gateway={route.gateway}"]
        if route.metric:
            lines.append(f"Metric={route.metric}")
    return lines


def balance_tables(wan: WanConfig, items: dict[str, InterfaceConfig]) -> dict[str, int]:
    """WAN -> номер таблицы (равен fwmark) в режиме balance; пусто в режиме failover."""
    if wan.mode != "balance":
        return {}
    names = sorted(name for name, cfg in items.items() if cfg.role == "wan")
    return {name: BALANCE_BASE + idx for idx, name in enumerate(names)}


def _balance_rule_sections(name: str, tables: dict[str, int]) -> str:
    """RoutingPolicyRule балансировки: локальные подсети остаются в main, fwmark -> таблица WAN."""
    names = list(tables)
    lines: list[str] = []
    if name == names[0]:
        lines += [
            "",
            "[RoutingPolicyRule]",
            "SuppressPrefixLength=0",
            "Table=main",
            "Priority=21999",
        ]
    lines += [
        "",
        "[RoutingPolicyRule]",
        f"FirewallMark={tables[name]}",
        f"Table={tables[name]}",
        f"Priority={22001 + names.index(name)}",
    ]
    return "\n".join(lines)


def render_wan(cfg: InterfaceConfig, metric: int | None, table: int | None = None) -> str:
    """WAN-файл; метрика задаёт приоритет failover, table — таблицу для балансировки."""
    if cfg.ipv4 == "pppoe" or (metric is None and table is None):
        return render_network(cfg)
    if cfg.ipv4 == "dhcp":
        text = render_network(cfg).rstrip("\n")
        if table is None:
            return f"{text}\nRouteMetric={metric}\n"
        lines = [text, f"RouteMetric={metric}", "", "[Route]", "Gateway=_dhcp4", f"Table={table}"]
        return "\n".join(lines) + "\n"
    lines = [HEADER, "[Match]", f"Name={cfg.name}", *link_lines(cfg)]
    lines += ["", "[Network]", f"Address={cfg.address}"]
    lines += [f"DNS={server}" for server in cfg.dns]
    if cfg.mtu:
        lines.append(f"MTUSize={cfg.mtu}")
    lines += ["", "[Route]", f"Gateway={cfg.gateway}"]
    if metric is not None:
        lines.append(f"Metric={metric}")
    if table is not None:
        lines += ["", "[Route]", f"Gateway={cfg.gateway}", f"Table={table}"]
    lines.append("")
    return "\n".join(lines)


def render_ppp_peers(cfg: InterfaceConfig) -> str:
    """Файл /etc/ppp/peers (ставится с правами 600: содержит пароль)."""
    lines = [
        HEADER,
        "plugin rp-pppoe.so",
        cfg.name,
        f"ifname ppp-{cfg.name}",
        f'user "{cfg.pppoe_username}"',
    ]
    if cfg.pppoe_password:
        lines.append(f'password "{cfg.pppoe_password}"')
    lines += ["noauth", "nodetach", "defaultroute", "persist", "maxfail 0", "holdoff 5"]
    if cfg.mtu:
        lines += [f"mtu {cfg.mtu}", f"mru {cfg.mtu}"]
    return "\n".join(lines) + "\n"


def render_ppp_service(cfg: InterfaceConfig) -> str:
    unit = f"altrouter-ppp-{cfg.name}"
    lines = [
        HEADER,
        "[Unit]",
        f"Description=PPPoE {cfg.name} (AltRouter)",
        "After=network-online.target",
        "Wants=network-online.target",
        "",
        "[Service]",
        "Type=simple",
        f"ExecStart=/usr/sbin/pppd call {unit}",
        "Restart=on-failure",
        "RestartSec=5",
        "",
        "[Install]",
        "WantedBy=multi-user.target",
        "",
    ]
    return "\n".join(lines)


def render_slave_network(port: str, bridge: str) -> str:
    lines = [HEADER, "[Match]", f"Name={port}", "", "[Network]", f"Bridge={bridge}", ""]
    return "\n".join(lines)


def render_bridge_netdev(bridge: str) -> str:
    lines = [HEADER, "[NetDev]", f"Name={bridge}", "Kind=bridge", ""]
    return "\n".join(lines)


def render_bridge_network(seg: SegmentConfig, routes: list[StaticRoute]) -> str:
    bridge = bridge_name(seg.id)
    lines = [HEADER, "[Match]", f"Name={bridge}", "", "[Network]", f"Address={seg.address}"]
    lines += _route_sections(routes)
    lines.append("")
    return "\n".join(lines)


def render_wg_netdev(wg: WireguardInterface) -> str:
    lines = [
        HEADER,
        "[NetDev]",
        f"Name={wg_iface_name(wg.id)}",
        "Kind=wireguard",
        "",
        "[WireGuard]",
        f"ListenPort={wg.listen_port}",
    ]
    if wg.route_mode != "none":
        lines.append(f"FwMark={wg.table_id}")
    if wg.private_key:
        lines.append(f"PrivateKey={wg.private_key}")
    if wg.mtu:
        lines.append(f"MTU={wg.mtu}")
    for peer in wg.peers:
        suffix = f" ({peer.comment})" if peer.comment else ""
        lines += ["", f"#{peer.name}{suffix}", "[WireGuardPeer]"]
        if peer.public_key:
            lines.append(f"PublicKey={peer.public_key}")
        if peer.preshared_key:
            lines.append(f"PresharedKey={peer.preshared_key}")
        lines.append(f"AllowedIPs={','.join(peer.allowed_ips)}")
        if peer.endpoint:
            lines.append(f"Endpoint={peer.endpoint}")
        if peer.keepalive:
            lines.append(f"PersistentKeepalive={peer.keepalive}")
    lines.append("")
    return "\n".join(lines)


def render_wg_network(
    wg: WireguardInterface, devices: list[tuple[str, str]] | None = None
) -> str:
    """Адрес туннеля и маршрутизация.

    none — только AllowedIPs-маршруты networkd; all — весь трафик, devices — выбранные
    источники: маршрут по умолчанию в таблице туннеля, защита от цикла — схема wg-quick
    (fwmark → main, всё кроме default → main), приоритет 1–99 задаёт порядок ip rule.
    """
    lines = [
        HEADER,
        "[Match]",
        f"Name={wg_iface_name(wg.id)}",
        "",
        "[Network]",
        f"Address={wg.address}",
        "IPForward=ipv4",
    ]
    if wg.route_mode != "none":
        table = wg.table_id
        lines += ["", "[Route]", "Destination=0.0.0.0/0", f"Table={table}"]
        froms = [""] if wg.route_mode == "all" else [dev for dev, _net in devices or []]
        for source in froms:
            prefix = [f"From={source}"] if source else []
            lines += [
                "",
                "[RoutingPolicyRule]",
                *prefix,
                f"FirewallMark={table}",
                "Table=main",
                "Priority=10",
                "",
                "[RoutingPolicyRule]",
                *prefix,
                "SuppressPrefixLength=0",
                "Table=main",
                "Priority=15",
                "",
                "[RoutingPolicyRule]",
                *prefix,
                f"Table={table}",
                f"Priority={100 + (wg.priority or 0)}",
            ]
    lines.append("")
    return "\n".join(lines)


# ---------- рендер dnsmasq ----------


def render_dnsmasq(state: dict) -> str:
    items: dict[str, InterfaceConfig] = state["items"]
    segments: list[SegmentConfig] = state["segments"]

    lines = ["# Сгенерировано AltRouter (dnsmasq) — не редактировать вручную"]
    if not segments:
        return "\n".join(lines + ["port=0", "# сегменты не настроены, DNS и DHCP выключены"]) + "\n"

    lines += ["bind-dynamic", "no-resolv"]
    servers: list[str] = []
    for cfg in items.values():
        if cfg.role == "wan":
            for server in cfg.dns:
                if server not in servers:
                    servers.append(server)
    if not servers:
        servers = ["1.1.1.1", "8.8.8.8"]
    lines += [f"server={server}" for server in servers]
    lines += ["domain=altrouter.lan", "expand-hosts", "local=/altrouter.lan/", "dhcp-authoritative"]

    for seg in sorted(segments, key=lambda s: s.id):
        lines += ["", f"# сегмент {seg.name} ({seg.address})"]
        lines.append(f"interface={bridge_name(seg.id)}")
        if seg.dhcp.enabled:
            lines.append(
                f"dhcp-range=set:{seg.id},{seg.dhcp.pool_start},{seg.dhcp.pool_end},"
                f"{seg.dhcp.lease_hours}h"
            )
            if seg.dhcp.dns:
                lines.append(f"dhcp-option=tag:{seg.id},option:dns-server,{','.join(seg.dhcp.dns)}")

    for seg in sorted(segments, key=lambda s: s.id):
        for res in seg.reservations:
            parts = [res.mac, res.ip]
            if res.hostname:
                parts.append(res.hostname)
            lines.append("dhcp-host=" + ",".join(parts))

    dns_records: list[DnsRecord] = state.get("dns") or []
    if dns_records:
        lines += ["", "# локальные DNS-имена"]
        for rec in dns_records:
            suffix = f" # {rec.comment}" if rec.comment else ""
            lines.append(f"host-record={rec.hostname},{rec.ip}{suffix}")

    return "\n".join(lines) + "\n"


# ---------- рендер nftables ----------


def _rule_matchers(rule: FirewallRule, iface: str) -> str:
    """nft-условия правила: интерфейс зоны, протокол/порты, адреса источника и приёмника."""
    parts = [f'iifname "{iface}"']
    if rule.proto in ("tcp", "udp"):
        if rule.src_port:
            parts.append(f"{rule.proto} sport {rule.src_port}")
        if rule.dst_port:
            parts.append(f"{rule.proto} dport {rule.dst_port}")
    if rule.src_ip:
        parts.append(f"ip saddr {rule.src_ip}")
    if rule.dst_ip:
        parts.append(f"ip daddr {rule.dst_ip}")
    return " ".join(parts)


def _rule_comment(rule: FirewallRule, index: int) -> str:
    return f"правило {index}" + (f" ({rule.comment})" if rule.comment else "")


def _dnat_lines(
    forwards: list[PortForward],
    wan_names: list[str],
    items: dict[str, InterfaceConfig],
    segments: list[SegmentConfig],
) -> tuple[list[str], list[str]]:
    """Пары (правила prerouting DNAT, встречные accept-правила forward)."""
    prerouting: list[str] = []
    accepts: list[str] = []
    bridges = [bridge_name(seg.id) for seg in segments]
    for fw in forwards:
        egress = resolve_forward_egress(fw, items, segments)
        targets = [ppp_iface(items[fw.wan])] if fw.wan else wan_names
        comment = f"DNAT {fw.proto}/{fw.port}" + (f" ({fw.comment})" if fw.comment else "")
        to = f"{fw.to_ip}:{fw.to_port}" if fw.to_port else fw.to_ip
        dport = fw.to_port or fw.port
        for wan in targets:
            for proto in ("tcp", "udp") if fw.proto == "both" else (fw.proto,):
                prerouting.append(
                    f'        iifname "{wan}" {proto} dport {fw.port} dnat to {to} '
                    f'comment "{comment}"'
                )
                accepts.append(
                    f'        iifname "{wan}" oifname "{egress}" ip daddr {fw.to_ip} '
                    f'{proto} dport {dport} accept comment "{comment}"'
                )
                if bridges:
                    in_bridges = ", ".join(f'"{b}"' for b in bridges)
                    prerouting.append(
                        f'        iifname {{ {in_bridges} }} fib daddr type local '
                        f'{proto} dport {fw.port} dnat to {to} '
                        f'comment "DNAT hairpin {comment}"'
                    )
                    accepts.append(
                        f'        iifname {{ {in_bridges} }} oifname "{egress}" ip daddr {fw.to_ip} '
                        f'{proto} dport {dport} accept comment "DNAT hairpin {comment}"'
                    )
    return prerouting, accepts


def _balance_nft(
    wan: WanConfig,
    tables: dict[str, int],
    lan_ifaces: list[str],
    ingress: dict[str, int],
) -> list[str]:
    """Таблица mangle: новые соединения LAN распределяются по WAN хэшем (jhash) в ct mark.

    Входящие WAN-соединения получают метку своего WAN — ответы уходят тем же интерфейсом.
    """
    names = list(tables)
    total = sum(wan.policies[n].weight if n in wan.policies else 1 for n in names)
    lines = [
        "table ip altrouter_balance {",
        "    chain prerouting {",
        "        type filter hook prerouting priority mangle; policy accept;",
    ]
    if lan_ifaces:
        in_lan = ", ".join(f'"{i}"' for i in lan_ifaces)
        lines.append(
            f"        iifname {{ {in_lan} }} fib daddr type local accept "
            'comment "hairpin: не балансировать локальные адреса"'
        )
    acc = 0
    for name in names:
        acc += wan.policies[name].weight if name in wan.policies else 1
        tail = (
            ""
            if acc == total
            else f"jhash ip saddr . ip daddr . th sport . th dport mod {total} lt {acc} "
        )
        tail_any = "" if acc == total else f"jhash ip saddr . ip daddr mod {total} lt {acc} "
        for iface in lan_ifaces:
            comment = f"балансировка {iface} -> WAN {name}"
            lines.append(
                f'        iifname "{iface}" ct state new ct mark 0 meta l4proto {{ tcp, udp }} '
                f"{tail}"
                f"ct mark set {tables[name]} comment \"{comment}\""
            )
            lines.append(
                f'        iifname "{iface}" ct state new ct mark 0 meta l4proto != {{ tcp, udp }} '
                f"{tail_any}"
                f"ct mark set {tables[name]} comment \"{comment}\""
            )
    for iface, tbl in ingress.items():
        lines.append(
            f'        iifname "{iface}" ct state new ct mark 0 ct mark set {tbl} '
            f'comment "симметрия ответов {iface}"'
        )
    lines += [
        '        ct mark != 0 meta mark set ct mark comment "марка соединения -> маршрут"',
        "    }",
    "    chain output {",
    "        type route hook output priority mangle; policy accept;",
        '        ct mark != 0 meta mark set ct mark comment "марка соединения -> маршрут: локальные ответы"',
        "    }",
        "}",
        "",
    ]
    return lines


def render_nftables(state: dict, mgmt: str) -> str:
    items: dict[str, InterfaceConfig] = state["items"]
    segments: list[SegmentConfig] = state["segments"]
    rules: list[FirewallRule] = state.get("rules") or []
    forwards: list[PortForward] = state.get("forwards") or []

    wan_names = sorted(ppp_iface(cfg) for cfg in items.values() if cfg.role == "wan")
    tables = balance_tables(state["wan"], items)
    seg_list = sorted(segments, key=lambda s: s.id)
    wg_list = [w for w in state.get("wireguard") or [] if w.enabled]
    wg_named = [(wg, wg_iface_name(wg.id)) for wg in wg_list]
    lan_direct = sorted(
        name
        for name, cfg in items.items()
        if cfg.role == "lan" and segment_of_port(segments, name) is None
    )

    def rule_lines(direction: str) -> list[str]:
        lines: list[str] = []
        for index, rule in enumerate(rules, start=1):
            if rule.direction != direction:
                continue
            comment = _rule_comment(rule, index)
            verdict = "accept" if rule.action == "allow" else "drop"
            for iface in zone_interfaces(rule.zone, items, segments):
                lines.append(
                    f'        {_rule_matchers(rule, iface)} {verdict} comment "{comment}"'
                )
        return lines

    dnat_prerouting, dnat_accepts = _dnat_lines(forwards, wan_names, items, segments)

    lines = [
        "#!/usr/sbin/nft -f",
        "# Сгенерировано AltRouter (nftables) — не редактировать вручную",
        "flush ruleset",
        "",
        "table inet altrouter_filter {",
        "    chain input {",
        "        type filter hook input priority filter; policy drop;",
        '        iifname "lo" accept',
        "        ct state invalid drop",
        "        ct state established,related accept",
        "        meta l4proto icmp accept",
        "        meta l4proto ipv6-icmp accept",
    ]
    if mgmt:
        lines.append(f'        iifname "{mgmt}" accept comment "управляющий интерфейс"')
    lines += rule_lines("input")
    for wg, _name in wg_named:
        for wan in wan_names:
            lines.append(
                f'        iifname "{wan}" udp dport {wg.listen_port} accept '
                f'comment "WireGuard {wg.id}"'
            )
    for seg in seg_list:
        lines.append(f'        iifname "{bridge_name(seg.id)}" accept comment "сегмент {seg.id}"')
    for name in lan_direct:
        lines.append(f'        iifname "{name}" accept comment "LAN без сегмента"')
    lines += [
        "    }",
        "",
        "    chain forward {",
        "        type filter hook forward priority filter; policy drop;",
        "        ct state invalid drop",
        "        ct state established,related accept",
        "        meta l4proto icmp accept",
        "        meta l4proto ipv6-icmp accept",
    ]
    lines += dnat_accepts
    lines += rule_lines("forward")
    for seg in seg_list:
        for wan in wan_names:
            lines.append(
                f'        iifname "{bridge_name(seg.id)}" oifname "{wan}" accept '
                f'comment "сегмент {seg.id} -> WAN {wan}"'
            )
    for wg, name in wg_named:
        for seg in seg_list:
            bridge = bridge_name(seg.id)
            lines.append(
                f'        iifname "{bridge}" oifname "{name}" accept '
                f'comment "сегмент {seg.id} -> VPN {wg.id}"'
            )
            lines.append(
                f'        iifname "{name}" oifname "{bridge}" accept '
                f'comment "VPN {wg.id} -> сегмент {seg.id}"'
            )
        for wan in wan_names:
            lines.append(
                f'        iifname "{name}" oifname "{wan}" accept '
                f'comment "VPN {wg.id} -> WAN {wan}"'
            )
        if wg.route_mode == "devices":
            for device, _subnet in resolve_wg_devices(wg, items, segments):
                lines.append(
                    f'        ip saddr {device} oifname "{name}" accept '
                    f'comment "VPN {wg.id}: устройство {device}"'
                )
    lines += [
        "    }",
        "}",
        "",
        "table ip altrouter_nat {",
        "    chain prerouting {",
        "        type nat hook prerouting priority dstnat; policy accept;",
    ]
    lines += dnat_prerouting
    lines += [
        "    }",
        "    chain postrouting {",
        "        type nat hook postrouting priority srcnat; policy accept;",
    ]
    for seg in seg_list:
        subnet = ipaddress.ip_interface(seg.address).network
        for wan in wan_names:
            rule = f'ip saddr {subnet} oifname "{wan}" masquerade'
            comment = f"сегмент {seg.id}"
            lines.append(f'        {rule} comment "{comment}"')
        bridge = bridge_name(seg.id)
        lines.append(
            f'        iifname "{bridge}" oifname "{bridge}" ip saddr {subnet} masquerade '
            f'comment "hairpin сегмент {seg.id}"'
        )
        other_bridges = ", ".join(
            f'"{bridge_name(s.id)}"' for s in seg_list if s.id != seg.id
        )
        if other_bridges:
            lines.append(
                f'        iifname "{bridge}" oifname {{ {other_bridges} }} ip saddr {subnet} masquerade '
                f'comment "hairpin сегмент {seg.id} -> другие сегменты"'
            )
    for wg, name in wg_named:
        for seg in seg_list:
            subnet = ipaddress.ip_interface(seg.address).network
            lines.append(
                f'        ip saddr {subnet} oifname "{name}" masquerade '
                f'comment "сегмент {seg.id} -> VPN {wg.id}"'
            )
        for peer in wg.peers:
            for subnet in peer.allowed_ips:
                for wan in wan_names:
                    lines.append(
                        f'        ip saddr {subnet} oifname "{wan}" masquerade '
                        f'comment "VPN {wg.id}: пир {peer.name}"'
                    )
        if wg.route_mode == "devices":
            for device, _subnet in resolve_wg_devices(wg, items, segments):
                lines.append(
                    f'        ip saddr {device} oifname "{name}" masquerade '
                    f'comment "VPN {wg.id}: устройство {device}"'
                )
    lines += ["    }", "}", ""]
    if tables:
        lines += _balance_nft(
            state["wan"],
            tables,
            [bridge_name(seg.id) for seg in seg_list] + lan_direct,
            {ppp_iface(items[name]): tbl for name, tbl in tables.items()},
        )
    return "\n".join(lines)


# ---------- запись staging ----------


def compose_staging(staging_dir: Path, state: dict, mgmt: str) -> None:
    """Атомарно приводит staging-каталог к полному набору файлов для root-хелпера."""
    items: dict[str, InterfaceConfig] = state["items"]
    segments: list[SegmentConfig] = state["segments"]
    routes: list[StaticRoute] = state["routes"]
    wan: WanConfig = state["wan"]

    routes_by_iface: dict[str, list[StaticRoute]] = {}
    for route in routes:
        egress = resolve_route_egress(route, items, segments)
        routes_by_iface.setdefault(egress, []).append(route)

    tables = balance_tables(wan, items)

    files: dict[str, str] = {}
    for name, cfg in items.items():
        if cfg.role == "off":
            continue
        seg = segment_of_port(segments, name)
        body: str
        if seg is not None:
            body = render_slave_network(name, bridge_name(seg.id))
        elif cfg.role == "wan":
            body = render_wan(
                cfg, None if cfg.ipv4 == "pppoe" else wan.metric_for(name), tables.get(name)
            )
        else:
            body = render_network(cfg)
        attached = routes_by_iface.get(name)
        if attached:
            body = body.rstrip("\n") + "\n" + "\n".join(_route_sections(attached)) + "\n"
        if name in tables:
            body = body.rstrip("\n") + "\n" + _balance_rule_sections(name, tables) + "\n"
        files[network_file_name(name)] = body
        if cfg.role == "wan" and cfg.ipv4 == "pppoe":
            base = f"altrouter-ppp-{name}"
            files[f"{base}.peers"] = render_ppp_peers(cfg)
            files[f"{base}.service"] = render_ppp_service(cfg)

    for seg in segments:
        bridge = bridge_name(seg.id)
        files[f"{MANAGED_PREFIX}{bridge}.netdev"] = render_bridge_netdev(bridge)
        files[f"{MANAGED_PREFIX}{bridge}.network"] = render_bridge_network(
            seg, routes_by_iface.get(bridge, [])
        )

    for wg in state.get("wireguard") or []:
        name = wg_iface_name(wg.id)
        files[f"{MANAGED_PREFIX}{name}.netdev"] = render_wg_netdev(wg)
        devices = resolve_wg_devices(wg, items, segments) if wg.route_mode == "devices" else []
        files[f"{MANAGED_PREFIX}{name}.network"] = render_wg_network(wg, devices)

    files[DNSMASQ_FILE] = render_dnsmasq(state)
    files[NFTABLES_FILE] = render_nftables(state, mgmt)

    staging_dir.mkdir(parents=True, exist_ok=True)
    for path in staging_dir.iterdir():
        if path.is_file() and (
            path.suffix in STAGING_SUFFIXES or path.name in (DNSMASQ_FILE, NFTABLES_FILE)
        ):
            path.unlink()
    for fname, text in files.items():
        tmp = staging_dir / f".{fname}.tmp"
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(staging_dir / fname)
