import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

from ..config import management_iface
from .composer import (
    DNSMASQ_FILE,
    NFTABLES_FILE,
    STAGING_SUFFIXES,
    compose_staging,
    validate_state,
)
from .errors import ApplyError, NetworkError
from .firewall import DnsRecord, FirewallRule, PortForward
from .models import InterfaceConfig
from .segments import SegmentConfig, StaticRoute, WanConfig
from .wireguard import WireguardInterface

__all__ = ["ApplyError", "InterfaceManager", "NetworkError"]

SECTION_KEYS = ("items", "segments", "routes", "wan", "rules", "forwards", "dns", "wireguard")


def sudo_applier() -> None:
    """Продовый applier: root-хелпер через sudo (белый список sudoers)."""
    default_cmd = "sudo -n /usr/local/sbin/altrouter-netapply"
    command = os.environ.get("ALTROUTER_NETAPPLY", default_cmd).split()
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired as e:
        raise ApplyError("применение конфигурации превысило таймаут") from e
    except OSError as e:
        raise ApplyError(f"не удалось запустить применение конфигурации: {e}") from e
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise ApplyError(f"применение завершилось с кодом {proc.returncode}: {detail}")


def _dump_state(state: dict) -> dict:
    return {
        "items": {name: cfg.model_dump() for name, cfg in state["items"].items()},
        "segments": [seg.model_dump() for seg in state["segments"]],
        "routes": [route.model_dump() for route in state["routes"]],
        "wan": state["wan"].model_dump(),
        "rules": [rule.model_dump() for rule in state.get("rules") or []],
        "forwards": [fw.model_dump() for fw in state.get("forwards") or []],
        "dns": [rec.model_dump() for rec in state.get("dns") or []],
        "wireguard": [wg.model_dump() for wg in state.get("wireguard") or []],
    }


def _parse_state(raw: dict) -> dict:
    return {
        "items": {name: InterfaceConfig(**cfg) for name, cfg in (raw.get("items") or {}).items()},
        "segments": [SegmentConfig(**seg) for seg in raw.get("segments") or []],
        "routes": [StaticRoute(**route) for route in raw.get("routes") or []],
        "wan": WanConfig(**(raw.get("wan") or {})),
        "rules": [FirewallRule(**rule) for rule in raw.get("rules") or []],
        "forwards": [PortForward(**fw) for fw in raw.get("forwards") or []],
        "dns": [DnsRecord(**rec) for rec in raw.get("dns") or []],
        "wireguard": [WireguardInterface(**wg) for wg in raw.get("wireguard") or []],
    }


class InterfaceManager:
    """Желаемое состояние роутера + транзакционное применение с откатом.

    Файлы в config_dir/network:
      network.json  — подтверждённое (коммитнутое) состояние;
      staging/      — текущие сгенерированные файлы (networkd, dnsmasq, nftables);
      backups/      — снимок staging на момент каждой транзакции;
      pending.json  — незавершённая транзакция (ожидает подтверждения или отката);
      journal.jsonl — журнал транзакций.

    Состояние (с этапа 4): items (интерфейсы), segments (LAN-сегменты),
    routes (статические маршруты), wan (приоритеты и Ping Check),
    rules (файрвол), forwards (DNAT), dns (локальные имена).
    """

    def __init__(
        self,
        config_dir: Path,
        applier=None,
        mgmt_iface: str | None = None,
        confirm_timeout: float | None = None,
    ):
        self.network_dir = Path(config_dir) / "network"
        self.staging_dir = self.network_dir / "staging"
        self.backups_dir = self.network_dir / "backups"
        self.state_path = self.network_dir / "network.json"
        self.pending_path = self.network_dir / "pending.json"
        self.journal_path = self.network_dir / "journal.jsonl"
        self.applier = applier or sudo_applier
        self.mgmt = mgmt_iface or management_iface()
        if confirm_timeout is None:
            confirm_timeout = float(os.environ.get("ALTROUTER_CONFIRM_TIMEOUT", "180"))
        self.confirm_timeout = confirm_timeout
        self.state_listeners: list = []
        self._lock = threading.Lock()
        self._timer_task = None
        self.network_dir.mkdir(parents=True, exist_ok=True)
        self._recover()

    # ---------- публичный API ----------

    def snapshot(self) -> dict:
        with self._lock:
            self._expire_if_due_locked()
            state = _dump_state(self._load_state())
            return {
                **state,
                "management": self.mgmt,
                "pending": self._pending_status(self._load_pending()),
            }

    def status(self) -> dict:
        with self._lock:
            self._expire_if_due_locked()
            return {
                "pending": self._pending_status(self._load_pending()),
                "confirm_timeout": self.confirm_timeout,
            }

    def validate(self, items: dict[str, InterfaceConfig]) -> None:
        with self._lock:
            self._expire_if_due_locked()
            state = self._load_state()
            state["items"] = items
            validate_state(state, mgmt=self.mgmt)

    def apply(self, items: dict[str, InterfaceConfig], username: str) -> dict:
        """Применение раздела «Интернет» (интерфейсы); остальные разделы — из коммита."""
        return self.apply_sections({"items": items}, username)

    def apply_sections(self, sections: dict, username: str) -> dict:
        """Применяет переданные разделы состояния поверх подтверждённого."""
        with self._lock:
            self._expire_if_due_locked()
            if self._load_pending() is not None:
                raise NetworkError("Сначала подтвердите или откатите текущие изменения")
            state = self._load_state()
            for key in SECTION_KEYS:
                if key in sections and sections[key] is not None:
                    state[key] = sections[key]
            return self._apply_state_locked(state, username)

    def confirm(self) -> dict:
        with self._lock:
            pending = self._load_pending()
            if pending is None:
                raise NetworkError("Нет изменений, ожидающих подтверждения")
            self._timer_task = None
            self._write_json(self.state_path, pending["new_state"])
            self.pending_path.unlink(missing_ok=True)
            self._journal(
                "committed", pending["id"], pending["username"], items=pending["new_state"]["items"]
            )
            self._notify_locked(_parse_state(pending["new_state"]))
            return {"ok": True}

    def rollback(self, reason: str = "по решению оператора") -> dict:
        with self._lock:
            return self._rollback_locked(reason)

    def effective_state(self) -> dict:
        """Состояние, действующее сейчас: незавершённая транзакция важнее коммита."""
        with self._lock:
            self._expire_if_due_locked()
            return self._effective_state_locked()

    def log_event(self, action: str, **extra) -> None:
        """Служебная запись в журнал (например, переподнятие интерфейса Ping Check)."""
        self._journal(action, "-", "system", **extra)

    def journal_entry(self, action: str, username: str, **extra) -> None:
        """Запись действия оператора в журнал изменений."""
        self._journal(action, "-", username, **extra)

    def journal(self, limit: int = 100) -> list[dict]:
        """Последние записи журнала изменений (хвост файла)."""
        if not self.journal_path.exists():
            return []
        lines = self.journal_path.read_text(encoding="utf-8").splitlines()
        entries = []
        for line in lines[-limit:]:
            if line.strip():
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return entries

    # ---------- внутреннее ----------

    def _apply_state_locked(self, state: dict, username: str) -> dict:
        validate_state(state, mgmt=self.mgmt)

        tx_id = uuid.uuid4().hex[:12]
        backup_dir = self.backups_dir / f"{int(time.time())}-{tx_id}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        self._backup_staging_locked(backup_dir)

        compose_staging(self.staging_dir, state, self.mgmt)
        try:
            self.applier()
        except ApplyError as e:
            self._journal("apply_failed", tx_id, username, error=str(e))
            self._restore_staging_locked(backup_dir)
            try:
                self.applier()
            except ApplyError:
                pass
            raise

        now = time.time()
        new_state = _dump_state(state)
        pending = {
            "id": tx_id,
            "username": username,
            "started_at": now,
            "deadline": now + self.confirm_timeout,
            "new_state": new_state,
            "new_items": new_state["items"],
            "backup_dir": str(backup_dir),
        }
        self._write_json(self.pending_path, pending)
        self._journal(
            "applied",
            tx_id,
            username,
            items=new_state["items"],
            segments=new_state["segments"],
            routes=new_state["routes"],
            wan=new_state["wan"],
            rules=new_state["rules"],
            forwards=new_state["forwards"],
            dns=new_state["dns"],
        )
        self._start_timer(tx_id, pending["deadline"])
        self._notify_locked(state)
        return self._pending_status(pending)

    def _rollback_locked(self, reason: str) -> dict:
        pending = self._load_pending()
        if pending is None:
            raise NetworkError("Нет изменений для отката")
        self._timer_task = None

        backup_dir = Path(pending.get("backup_dir") or "")
        if backup_dir.is_dir():
            self._restore_staging_locked(backup_dir)
        else:
            compose_staging(self.staging_dir, _parse_state({}), self.mgmt)
        system_restored = True
        try:
            self.applier()
        except ApplyError:
            system_restored = False

        self.pending_path.unlink(missing_ok=True)
        self._journal(
            "rolled_back",
            pending["id"],
            pending["username"],
            reason=reason,
            system_restored=system_restored,
        )
        self._notify_locked(self._load_state())
        return {"ok": True, "system_restored": system_restored}

    def _recover(self) -> None:
        if not self.pending_path.exists():
            return
        try:
            self._rollback_locked("перезапуск сервиса")
        except NetworkError:
            self.pending_path.unlink(missing_ok=True)

    def _expire_if_due_locked(self) -> None:
        pending = self._load_pending()
        if pending is not None and time.time() >= pending["deadline"]:
            self._rollback_locked(f"истёк интервал подтверждения ({int(self.confirm_timeout)} с)")

    def _expire_transaction(self, tx_id: str) -> None:
        with self._lock:
            pending = self._load_pending()
            if pending is None or pending.get("id") != tx_id:
                return
            self._rollback_locked(f"истёк интервал подтверждения ({int(self.confirm_timeout)} с)")

    def _effective_state_locked(self) -> dict:
        pending = self._load_pending()
        if pending is not None:
            raw = pending.get("new_state")
            if raw is None:
                raw = {"items": pending.get("new_items") or {}}
            return _parse_state(raw)
        return self._load_state()

    def _notify_locked(self, state: dict) -> None:
        for listener in list(self.state_listeners):
            listener(state)

    def _is_managed(self, path: Path) -> bool:
        return path.suffix in STAGING_SUFFIXES or path.name in (DNSMASQ_FILE, NFTABLES_FILE)

    def _backup_staging_locked(self, backup_dir: Path) -> None:
        if not self.staging_dir.is_dir():
            return
        for path in self.staging_dir.iterdir():
            if path.is_file() and self._is_managed(path):
                shutil.copy2(path, backup_dir / path.name)

    def _restore_staging_locked(self, backup_dir: Path) -> None:
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        for path in self.staging_dir.iterdir():
            if path.is_file() and self._is_managed(path):
                path.unlink()
        for path in backup_dir.iterdir():
            if path.is_file():
                shutil.copy2(path, self.staging_dir / path.name)

    def _start_timer(self, tx_id: str, deadline: float) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._timer_task = loop.create_task(self._timer(tx_id, deadline))

    def schedule_confirm_timer(self, pending: dict | None) -> None:
        if pending:
            self._start_timer(pending["id"], pending["deadline"])

    async def _timer(self, tx_id: str, deadline: float) -> None:
        delay = deadline - time.time()
        if delay > 0:
            await asyncio.sleep(delay)
        await asyncio.to_thread(self._expire_transaction, tx_id)

    def _load_state(self) -> dict:
        if self.state_path.exists():
            return _parse_state(json.loads(self.state_path.read_text(encoding="utf-8")))
        return _parse_state({})

    def _load_pending(self) -> dict | None:
        if self.pending_path.exists():
            return json.loads(self.pending_path.read_text(encoding="utf-8"))
        return None

    @staticmethod
    def _pending_status(pending: dict | None) -> dict | None:
        if pending is None:
            return None
        keys = ("id", "username", "started_at", "deadline", "new_items")
        info = {key: pending[key] for key in keys}
        new_state = pending.get("new_state") or {}
        info["sections"] = {
            "segments": new_state.get("segments", []),
            "routes": new_state.get("routes", []),
            "wan": new_state.get("wan", {"policies": {}}),
            "rules": new_state.get("rules", []),
            "forwards": new_state.get("forwards", []),
            "dns": new_state.get("dns", []),
            "wireguard": new_state.get("wireguard", []),
        }
        info["seconds_left"] = max(0, int(pending["deadline"] - time.time()))
        return info

    def _write_json(self, path: Path, data: dict) -> None:
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    def _journal(self, action: str, tx_id: str, username: str, **extra) -> None:
        entry = {"ts": time.time(), "id": tx_id, "username": username, "action": action, **extra}
        with self.journal_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
