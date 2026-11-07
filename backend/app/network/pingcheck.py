"""Ping Check: фоновая проверка доступности WAN с переподнятием интерфейса при сбоях."""

import os
import re
import subprocess
import threading
import time

from .segments import PingCheck

PING_TIMEOUT_S = 5
LATENCY_RE = re.compile(r"time[=<]\s*([\d.]+)\s*ms", re.IGNORECASE)
ACTION_COOLDOWN_S = 60


def _default_ping(iface: str, target: str) -> tuple[bool, float | None]:
    cmd = ["ping", "-n", "-c", "1", "-W", "2", "-I", iface, target]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=PING_TIMEOUT_S)
    except (subprocess.TimeoutExpired, OSError):
        return False, None
    latency: float | None = None
    match = LATENCY_RE.search(proc.stdout)
    if match:
        latency = float(match.group(1))
    return proc.returncode == 0, latency


def _default_renew(iface: str) -> bool:
    default_cmd = "sudo -n /usr/bin/networkctl renew"
    command = os.environ.get("ALTROUTER_NETCTL", default_cmd).split() + [iface]
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=30)
    except (subprocess.TimeoutExpired, OSError):
        return False
    return proc.returncode == 0


class PingChecker:
    """Опрашивает включённые Ping Check-политики; при серии неудач переподнимает интерфейс."""

    def __init__(self, ping=None, renew=None, logger=None, clock=time.time):
        self._ping = ping or _default_ping
        self._renew = renew or _default_renew
        self._logger = logger or (lambda **kwargs: None)
        self._clock = clock
        self._lock = threading.Lock()
        self._policies: dict[str, PingCheck] = {}
        self._trackers: dict[str, dict] = {}
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    # ---------- публичный API ----------

    def configure(self, policies: dict[str, PingCheck]) -> None:
        with self._lock:
            self._policies = dict(policies)
            for iface, policy in self._policies.items():
                tracker = self._trackers.get(iface)
                if tracker is None:
                    tracker = {
                        "target": policy.target,
                        "interval_s": policy.interval_s,
                        "fail_threshold": policy.fail_threshold,
                        "next_due": 0.0,
                        "fails": 0,
                        "state": "unknown",
                        "last_check": None,
                        "latency_ms": None,
                        "last_action": None,
                    }
                    self._trackers[iface] = tracker
                else:
                    tracker["target"] = policy.target
                    tracker["interval_s"] = policy.interval_s
                    tracker["fail_threshold"] = policy.fail_threshold
            for iface in list(self._trackers):
                if iface not in self._policies:
                    del self._trackers[iface]

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="altrouter-pingcheck", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def run_once(self) -> None:
        now = self._clock()
        with self._lock:
            due = [(iface, dict(tracker)) for iface, tracker in self._trackers.items()]
        for iface, tracker in due:
            if now < tracker["next_due"]:
                continue
            ok, latency = self._ping(iface, tracker["target"])
            self._record(iface, ok, latency)

    def status(self) -> dict:
        with self._lock:
            return {
                iface: {
                    "target": tracker["target"],
                    "interval_s": tracker["interval_s"],
                    "fail_threshold": tracker["fail_threshold"],
                    "state": tracker["state"],
                    "fails": tracker["fails"],
                    "last_check": tracker["last_check"],
                    "latency_ms": tracker["latency_ms"],
                    "last_action": tracker["last_action"],
                }
                for iface, tracker in self._trackers.items()
            }

    # ---------- внутреннее ----------

    def _loop(self) -> None:
        while not self._stop_event.wait(1.0):
            try:
                self.run_once()
            except Exception:  # noqa: BLE001 — фоновый поток не должен падать
                continue

    def _record(self, iface: str, ok: bool, latency: float | None) -> None:
        action_iface = None
        with self._lock:
            tracker = self._trackers.get(iface)
            if tracker is None:
                return
            now = self._clock()
            tracker["last_check"] = now
            tracker["next_due"] = now + tracker["interval_s"]
            tracker["latency_ms"] = latency
            tracker["fails"] = 0 if ok else tracker["fails"] + 1
            if ok:
                tracker["state"] = "ok"
            elif tracker["fails"] >= tracker["fail_threshold"]:
                tracker["state"] = "fail"
                cooldown = max(ACTION_COOLDOWN_S, tracker["interval_s"] * tracker["fail_threshold"])
                if tracker["last_action"] is None or now - tracker["last_action"] >= cooldown:
                    tracker["last_action"] = now
                    tracker["fails"] = 0
                    action_iface = iface
            else:
                tracker["state"] = "checking"
        if action_iface is not None:
            self._renew(action_iface)
            self._logger(iface=action_iface)
