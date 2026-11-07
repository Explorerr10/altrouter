from app.monitor.clients import parse_arp, parse_leases
from app.monitor.stats import StatsCollector

ARP_TEXT = """IP address       HW type     Flags       HW address            Mask     Device
192.168.0.10     0x1         0x2         aa:bb:cc:dd:ee:01     *        enp9s0f0
192.168.0.11     0x1         0x0         aa:bb:cc:dd:ee:02     *        enp9s0f0
192.168.0.12     0x1         0x2         00:00:00:00:00:00     *        enp9s0f0
"""


def test_parse_arp():
    clients = parse_arp(ARP_TEXT)
    assert len(clients) == 2
    by_ip = {c["ip"]: c for c in clients}
    assert by_ip["192.168.0.10"]["active"] is True
    assert by_ip["192.168.0.10"]["mac"] == "aa:bb:cc:dd:ee:01"
    assert by_ip["192.168.0.10"]["interface"] == "enp9s0f0"
    assert by_ip["192.168.0.11"]["active"] is False


def test_parse_arp_empty():
    assert parse_arp("") == []


def test_parse_leases():
    leases = parse_leases("1760000000 aa:bb:cc:dd:ee:01 192.168.0.10 desktop01 01:aa:bb\n")
    assert leases == {"aa:bb:cc:dd:ee:01": "desktop01"}


def test_parse_leases_star_hostname():
    leases = parse_leases("1760000000 aa:bb:cc:dd:ee:02 192.168.0.11 * 01:aa:bb\n")
    assert leases == {}


def test_stats_snapshot_shape():
    snap = StatsCollector().snapshot()
    assert 0 <= snap["cpu_percent"] <= 100
    assert 0 <= snap["ram_percent"] <= 100
    assert isinstance(snap["interfaces"], dict)
    assert snap["ram_total_bytes"] > 0
