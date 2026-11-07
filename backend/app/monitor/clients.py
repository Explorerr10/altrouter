from pathlib import Path

LEASES_PATH = Path("/var/lib/misc/dnsmasq.leases")


def parse_arp(text: str) -> list[dict]:
    clients = []
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 6:
            continue
        ip, _, flags, mac, _, iface = parts[:6]
        if mac == "00:00:00:00:00:00":
            continue
        try:
            active = bool(int(flags, 16) & 0x2)
        except ValueError:
            active = False
        clients.append({"ip": ip, "mac": mac, "interface": iface, "active": active})
    return clients


def parse_leases(text: str) -> dict[str, str]:
    hostnames: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 4:
            _, mac, _, hostname = parts[:4]
            if hostname and hostname != "*":
                hostnames[mac.lower()] = hostname
    return hostnames


def clients_snapshot() -> list[dict]:
    try:
        arp_text = Path("/proc/net/arp").read_text()
    except OSError:
        arp_text = ""
    try:
        leases_text = LEASES_PATH.read_text()
    except OSError:
        leases_text = ""
    hostnames = parse_leases(leases_text)
    clients = []
    for entry in parse_arp(arp_text):
        entry["hostname"] = hostnames.get(entry["mac"].lower())
        clients.append(entry)
    clients.sort(key=lambda c: c["ip"])
    return clients
