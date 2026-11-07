import os
import socket

import psutil

from ..config import management_iface


def _is_physical(name: str) -> bool:
    return os.path.isdir(f"/sys/class/net/{name}/device")


def interfaces_snapshot() -> list[dict]:
    addrs = psutil.net_if_addrs()
    stats = psutil.net_if_stats()
    io = psutil.net_io_counters(pernic=True, nowrap=True)
    mgmt = management_iface()
    result = []
    for name in addrs:
        if name == "lo":
            continue
        ipv4 = [a.address for a in addrs[name] if a.family == socket.AF_INET]
        ipv6 = [
            a.address.split("%")[0] for a in addrs[name] if a.family == socket.AF_INET6
        ][:1]
        st = stats.get(name)
        counters = io.get(name)
        mac = next((a.address for a in addrs[name] if a.family == psutil.AF_LINK), None)
        result.append(
            {
                "name": name,
                "up": bool(st.isup) if st else False,
                "speed_mbps": st.speed if st else None,
                "mtu": st.mtu if st else None,
                "mac": mac,
                "ipv4": ipv4,
                "ipv6": ipv6,
                "rx_bytes": counters.bytes_recv if counters else 0,
                "tx_bytes": counters.bytes_sent if counters else 0,
                "management": name == mgmt,
                "physical": _is_physical(name),
            }
        )
    result.sort(key=lambda i: (not i["physical"], not i["management"], i["name"]))
    return result
