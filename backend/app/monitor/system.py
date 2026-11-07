import platform
import socket
import subprocess
import time
from pathlib import Path

import psutil

from ..config import management_iface
from ._compat import _getloadavg


def _read_first(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    return text or None


def _dmi(name: str) -> str | None:
    return _read_first(Path("/sys/class/dmi/id") / name)


def _os_pretty_name() -> str | None:
    release = Path("/etc/os-release")
    if not release.exists():
        return None
    for line in release.read_text().splitlines():
        if line.startswith("PRETTY_NAME="):
            return line.split("=", 1)[1].strip('"') or None
    return None


def _cpu_model() -> str | None:
    cpuinfo = Path("/proc/cpuinfo")
    if not cpuinfo.exists():
        return None
    for line in cpuinfo.read_text().splitlines():
        if line.startswith("model name"):
            return line.split(":", 1)[1].strip()
    return None


def _has_default_route() -> bool:
    route = Path("/proc/net/route")
    if not route.exists():
        return False
    try:
        lines = route.read_text().splitlines()[1:]
    except OSError:
        return False
    for line in lines:
        parts = line.split()
        if len(parts) > 1 and parts[1] == "00000000":
            return True
    return False


def _dns_ok() -> bool:
    try:
        result = subprocess.run(
            ["getent", "hosts", "debian.org"],
            timeout=3,
            check=False,
            capture_output=True,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _temperatures() -> dict[str, float]:
    try:
        sensors = psutil.sensors_temperatures()
    except (OSError, AttributeError):
        return {}
    result: dict[str, float] = {}
    for name, entries in sensors.items():
        for i, entry in enumerate(entries):
            key = entry.label or f"{name} {i}"
            if entry.current is not None:
                result[f"{key}"] = round(entry.current, 1)
    return result


def system_info() -> dict:
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    route = _has_default_route()
    load = _getloadavg()
    return {
        "hostname": socket.gethostname(),
        "model": _dmi("product_name"),
        "board": _dmi("board_name"),
        "os": _os_pretty_name() or f"{platform.system()} {platform.release()}",
        "kernel": platform.release(),
        "cpu_model": _cpu_model(),
        "cpu_cores": psutil.cpu_count(logical=False),
        "cpu_threads": psutil.cpu_count(logical=True),
        "ram_total_bytes": vm.total,
        "uptime_seconds": int(time.time() - psutil.boot_time()),
        "disk": {
            "total_bytes": disk.total,
            "used_bytes": disk.used,
            "percent": round(disk.percent, 1),
        },
        "temperatures": _temperatures(),
        "management_iface": management_iface(),
        "load_avg": load,
        "internet": {
            "default_route": route,
            "dns_ok": route and _dns_ok(),
        },
    }
