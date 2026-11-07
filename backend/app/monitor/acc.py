import ipaddress
import json
import subprocess
import threading
import time
from pathlib import Path

TABLE = "inet altrouter_acc"
NFT = "/usr/sbin/nft"
DUMP_TTL = 10.0


def _run(args, stdin=None):
    p = subprocess.run(args, input=stdin, capture_output=True, text=True)
    return p.returncode, p.stdout


def nft_cmd(*args):
    return ["sudo", "-n", NFT, *args]


def filter_ips(clients):
    ips = set()
    for c in clients:
        try:
            ips.add(str(ipaddress.IPv4Address(c["ip"])))
        except (KeyError, ValueError, TypeError):
            pass
    return sorted(ips)


def sync_script(ips):
    lines = [
        f"add table {TABLE}",
        f"add chain {TABLE} fwd {{ type filter hook forward priority 10; }}",
    ]
    for ip in ips:
        lines.append(f"add rule {TABLE} fwd ip saddr {ip} counter")
        lines.append(f"add rule {TABLE} fwd ip daddr {ip} counter")
    return "\n".join(lines) + "\n"


def parse_dump(obj):
    acc = {}
    for item in obj.get("nftables", []):
        rule = item.get("rule")
        if not rule:
            continue
        ip = None
        up = False
        for e in rule.get("expr", []):
            if "match" in e:
                m = e["match"]
                p = m.get("left", {}).get("payload", {})
                if p.get("field") in ("saddr", "daddr"):
                    cand = p.get("addr") or m.get("right")
                    try:
                        ipaddress.IPv4Address(cand)
                    except (ValueError, TypeError):
                        cand = None
                    ip, up = cand, p["field"] == "saddr"
            elif "counter" in e and ip:
                cur = acc.setdefault(ip, [0, 0])
                cur[0 if up else 1] += int(e["counter"].get("bytes", 0))
    return {ip: (v[0], v[1]) for ip, v in acc.items()}


class AccCollector:
    def __init__(self, config_dir, run=_run, clock=time.time):
        self._run = run
        self._clock = clock
        self._path = Path(config_dir) / "acc.json"
        self._lock = threading.Lock()
        self._totals = {}
        self._prev = {}
        self._speeds = {}
        self._ts = 0.0
        try:
            self._totals = json.loads(self._path.read_text()).get("totals", {})
        except (OSError, ValueError):
            pass

    def enrich(self, clients):
        with self._lock:
            self._tick(filter_ips(clients))
            if not self._speeds and not self._totals:
                return clients
            for c in clients:
                ip = c.get("ip")
                tot = self._totals.get(ip, [0, 0])
                spd = self._speeds.get(ip, [0, 0])
                c["rx_bps"], c["tx_bps"] = spd[1], spd[0]
                c["rx_total"], c["tx_total"] = tot[1], tot[0]
            return clients

    def _tick(self, ips):
        now = self._clock()
        if now - self._ts < DUMP_TTL and set(ips) == set(self._prev):
            return
        rc, out = self._run(nft_cmd("-j", "list", "table", TABLE))
        cur = None
        if rc == 0:
            try:
                cur = parse_dump(json.loads(out))
            except ValueError:
                cur = None
        if cur is None or set(cur) != set(ips):
            if self._sync(ips) != 0:
                return
            rc, out = self._run(nft_cmd("-j", "list", "table", TABLE))
            if rc != 0:
                return
            try:
                cur = parse_dump(json.loads(out))
            except ValueError:
                return
        dt = now - self._ts
        if not 0 < dt <= 30:
            dt = 0
        self._speeds = {}
        for ip, (up, dn) in cur.items():
            p = self._prev.get(ip)
            tot = self._totals.setdefault(ip, [0, 0])
            spd = [0, 0]
            for i, v in enumerate((up, dn)):
                delta = v - p[i] if p and v >= p[i] else v
                tot[i] += delta
                if dt:
                    spd[i] = delta / dt
            self._speeds[ip] = spd
        self._prev = cur
        self._ts = now
        self._save()

    def _sync(self, ips):
        self._run(nft_cmd("delete", "table", TABLE))
        return self._run(nft_cmd("-f", "-"), stdin=sync_script(ips))[0]

    def _save(self):
        try:
            self._path.write_text(json.dumps({"totals": self._totals}))
        except OSError:
            pass
