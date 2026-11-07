import time

import psutil

from ._compat import _getloadavg


class StatsCollector:
    def __init__(self) -> None:
        self._prev_io: dict | None = None
        self._prev_ts: float | None = None
        psutil.cpu_percent(interval=None)

    def snapshot(self) -> dict:
        now_mono = time.monotonic()
        cpu = psutil.cpu_percent(interval=None)
        per_core = psutil.cpu_percent(interval=None, percpu=True)
        vm = psutil.virtual_memory()
        swap = psutil.swap_memory()
        io = psutil.net_io_counters(pernic=True, nowrap=True)

        rates: dict[str, dict] = {}
        dt = now_mono - self._prev_ts if self._prev_ts is not None else 0.0
        if self._prev_io is not None and dt > 0:
            for name, counters in io.items():
                if name == "lo":
                    continue
                prev = self._prev_io.get(name)
                if prev is None:
                    continue
                rates[name] = {
                    "rx_bps": max(0.0, (counters.bytes_recv - prev.bytes_recv) / dt),
                    "tx_bps": max(0.0, (counters.bytes_sent - prev.bytes_sent) / dt),
                }
        self._prev_io = io
        self._prev_ts = now_mono

        return {
            "ts": time.time(),
            "cpu_percent": cpu,
            "cpu_per_core": per_core,
            "ram_percent": vm.percent,
            "ram_used_bytes": vm.used,
            "ram_total_bytes": vm.total,
            "swap_percent": swap.percent,
            "load_avg": _getloadavg(),
            "interfaces": rates,
        }
