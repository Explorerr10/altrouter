import json

from app.monitor.acc import AccCollector, filter_ips, parse_dump, sync_script
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


def dump_json(pairs):
    rules = [{"metainfo": {}}]
    for field, ip, b in pairs:
        rules.append({"rule": {"expr": [
            {"match": {"op": "==", "left": {"payload": {"protocol": "ip", "field": field}}, "right": ip}},
            {"counter": {"packets": 1, "bytes": b}},
        ]}})
    return {"nftables": rules}


class FakeNft:
    def __init__(self, dumps):
        self.dumps = list(dumps)
        self.syncs = 0

    def __call__(self, args, stdin=None):
        if stdin is not None:
            self.syncs += 1
            return (0, "")
        if "-j" in args:
            return self.dumps.pop(0) if self.dumps else (1, "")
        return (0, "")


def test_parse_dump():
    obj = dump_json([("saddr", "192.168.0.10", 100), ("daddr", "192.168.0.10", 300)])
    assert parse_dump(obj) == {"192.168.0.10": (100, 300)}


def test_filter_ips():
    ips = filter_ips([{"ip": "192.168.0.2"}, {"ip": "192.168.0.2"}, {"ip": "bad"}, {"ip": "10.0.0.1"}, {}])
    assert ips == ["10.0.0.1", "192.168.0.2"]


def test_sync_script():
    s = sync_script(["10.0.0.1"])
    assert "add table inet altrouter_acc" in s
    assert "hook forward priority 10" in s
    assert "ip saddr 10.0.0.1 counter" in s
    assert "ip daddr 10.0.0.1 counter" in s


def test_acc_enrich_flow(tmp_path):
    state = {"t": 100.0}
    nft = FakeNft([
        (0, json.dumps(dump_json([("saddr", "192.168.0.10", 100), ("daddr", "192.168.0.10", 300)]))),
        (0, json.dumps(dump_json([("saddr", "192.168.0.10", 1000), ("daddr", "192.168.0.10", 2000)]))),
        (0, json.dumps(dump_json([("saddr", "192.168.0.10", 350), ("daddr", "192.168.0.10", 800),
                                   ("saddr", "192.168.0.11", 0), ("daddr", "192.168.0.11", 0)]))),
    ])
    acc = AccCollector(tmp_path, run=nft, clock=lambda: state["t"])
    out = acc.enrich([{"ip": "192.168.0.10"}])
    assert nft.syncs == 0
    assert out[0]["tx_total"] == 100
    assert out[0]["rx_total"] == 300
    assert out[0]["tx_bps"] == 0
    assert out[0]["rx_bps"] == 0
    state["t"] = 110.0
    out = acc.enrich([{"ip": "192.168.0.10"}, {"ip": "192.168.0.11"}])
    assert nft.syncs == 1
    assert out[0]["tx_total"] == 350
    assert out[0]["rx_total"] == 800
    assert out[0]["tx_bps"] == 25
    assert out[0]["rx_bps"] == 50


def test_acc_reset_on_resync(tmp_path):
    state = {"t": 100.0}
    nft = FakeNft([
        (0, json.dumps(dump_json([("saddr", "192.168.0.10", 1000), ("daddr", "192.168.0.10", 2000)]))),
        (0, json.dumps(dump_json([("saddr", "192.168.0.10", 100), ("daddr", "192.168.0.10", 200)]))),
    ])
    acc = AccCollector(tmp_path, run=nft, clock=lambda: state["t"])
    acc.enrich([{"ip": "192.168.0.10"}])
    state["t"] = 110.0
    out = acc.enrich([{"ip": "192.168.0.10"}])
    assert nft.syncs == 0
    assert out[0]["tx_total"] == 1100
    assert out[0]["rx_total"] == 2200


def test_acc_persistence(tmp_path):
    state = {"t": 100.0}
    nft = FakeNft([(0, json.dumps(dump_json([("saddr", "192.168.0.10", 100), ("daddr", "192.168.0.10", 300)])))])
    AccCollector(tmp_path, run=nft, clock=lambda: state["t"]).enrich([{"ip": "192.168.0.10"}])
    nft2 = FakeNft([(1, "")])
    out = AccCollector(tmp_path, run=nft2, clock=lambda: state["t"]).enrich([{"ip": "192.168.0.10"}])
    assert out[0]["tx_total"] == 100
    assert out[0]["rx_total"] == 300
    assert out[0]["tx_bps"] == 0
    assert out[0]["rx_bps"] == 0


def test_acc_unavailable(tmp_path):
    acc = AccCollector(tmp_path, run=FakeNft([(1, "")]), clock=lambda: 0.0)
    out = acc.enrich([{"ip": "192.168.0.10"}])
    assert "rx_bps" not in out[0]
