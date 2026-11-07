import io
import ipaddress
import json
import os
import re
import socket
import ssl
import subprocess
import tarfile
import tempfile
from pathlib import Path

import psutil

OUTPUT_LIMIT = 65536
BACKUP_MEMBERS = ("config.json", "network/network.json", "network/journal.jsonl")
JOURNAL_UNITS = {
    "altrouter": ["-u", "altrouter"],
    "networkd": ["-u", "systemd-networkd"],
    "dnsmasq": ["-u", "dnsmasq"],
    "kernel": ["-k"],
}
SAFE_HOST = re.compile(r"^[A-Za-z0-9._-]{1,253}$")
SAFE_IFACE = re.compile(r"^[A-Za-z0-9._-]{1,15}$")
SAFE_FILTER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9()!=<>/.$_+|:-]*$")


class SystemError(ValueError):
    """Ожидаемая ошибка системной операции (показывается оператору)."""


def _decode(data) -> str:
    if data is None:
        return ""
    return data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data


def _atomic_write(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def run_cmd(args: list[str], timeout: int) -> str:
    """Вывод команды (хвост); таймаут не считается ошибкой диагностики."""
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        return (_decode(e.stdout) + _decode(e.stderr))[-OUTPUT_LIMIT:]
    except OSError as e:
        raise SystemError(f"Не удалось запустить {args[0]}: {e}") from e
    return ((proc.stdout or "") + (proc.stderr or ""))[-OUTPUT_LIMIT:]


def run_checked(args: list[str], timeout: int) -> str:
    """Команда, ненулевой код возврата которой является ошибкой."""
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise SystemError(f"Превышено время ожидания {args[0]}") from e
    except OSError as e:
        raise SystemError(f"Не удалось запустить {args[0]}: {e}") from e
    if proc.returncode != 0:
        detail = ((proc.stderr or "") + (proc.stdout or "")).strip()[-2000:]
        raise SystemError(f"{args[0]} завершился с кодом {proc.returncode}: {detail}")
    return proc.stdout or ""


def _ok(args: list[str]) -> bool:
    try:
        return subprocess.run(args, capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def diag_ping(host: str, count: int = 4) -> str:
    if not SAFE_HOST.match(host):
        raise SystemError("Недопустимый адрес узла")
    return run_cmd(["ping", "-c", str(count), "-W", "2", host], count * 3 + 5)


def diag_traceroute(host: str) -> str:
    if not SAFE_HOST.match(host):
        raise SystemError("Недопустимый адрес узла")
    return run_cmd(["traceroute", "-n", "-w", "2", "-q", "1", "-m", "20", host], 90)


def diag_tcpdump(iface: str, filter_text: str, seconds: int = 10) -> str:
    if not SAFE_IFACE.match(iface):
        raise SystemError("Недопустимое имя интерфейса")
    words = filter_text.split()
    for word in words:
        if not SAFE_FILTER.match(word):
            raise SystemError(f"Недопустимое выражение фильтра: {word!r}")
    args = ["sudo", "-n", "/usr/bin/tcpdump", "-nn", "-c", "200", "-i", iface, *words]
    return run_cmd(args, seconds + 5).strip()


def system_log(unit: str, lines: int = 200) -> str:
    if unit not in JOURNAL_UNITS:
        raise SystemError("Неизвестный журнал")
    lines = max(1, min(1000, lines))
    return run_cmd(
        ["journalctl", "--no-pager", "-o", "short-iso", "-n", str(lines), *JOURNAL_UNITS[unit]], 30
    )


def ssh_status() -> dict:
    info = {
        "active": _ok(["systemctl", "is-active", "ssh"]),
        "enabled": _ok(["systemctl", "is-enabled", "ssh"]),
        "port": None,
        "allow_subnet": None,
        "password_auth": True,
    }
    try:
        text = Path("/etc/ssh/sshd_config.d/altrouter.conf").read_text(encoding="utf-8")
    except OSError:
        return info
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "Port" and parts[1].isdigit():
            info["port"] = int(parts[1])
        elif parts and parts[0] == "PasswordAuthentication":
            info["password_auth"] = parts[1] == "yes"
        elif parts and parts[0] == "AllowUsers":
            for token in parts[1:]:
                if token.startswith("*@") and token not in ("*@127.0.0.0/8", "*@::1/128"):
                    info["allow_subnet"] = token[2:]
    return info


def ssh_set(enabled: bool) -> None:
    verb = "start" if enabled else "stop"
    state = "enable" if enabled else "disable"
    run_checked(["sudo", "-n", "/usr/bin/systemctl", verb, "ssh"], 30)
    run_checked(["sudo", "-n", "/usr/bin/systemctl", state, "ssh"], 30)


def ssh_apply(port: int, cidr: str | None, password_auth: bool = True) -> None:
    run_checked(
        [
            "sudo",
            "-n",
            "/usr/local/sbin/altrouter-ssh",
            "apply",
            str(port),
            cidr or "-",
            "yes" if password_auth else "no",
        ],
        60,
    )


def ssh_users() -> list[dict]:
    """Локальные учётные записи, которым разрешён вход: root и обычные пользователи."""
    users = []
    try:
        text = Path("/etc/passwd").read_text(encoding="utf-8")
    except OSError as e:
        raise SystemError("Не удалось прочитать список пользователей") from e
    for line in text.splitlines():
        parts = line.split(":")
        if len(parts) < 7:
            continue
        name, uid, shell = parts[0], parts[2], parts[6]
        if name != "root" and not (uid.isdigit() and int(uid) >= 1000):
            continue
        if shell.endswith(("nologin", "false")):
            continue
        users.append({"username": name, "uid": int(uid) if uid.isdigit() else 0})
    return users


def _ssh_keys(args: list[str], key: str | None = None) -> str:
    try:
        proc = subprocess.run(
            ["sudo", "-n", "/usr/local/sbin/altrouter-ssh", *args],
            capture_output=True,
            text=True,
            timeout=30,
            input=key,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        raise SystemError(f"Не удалось выполнить altrouter-ssh: {e}") from e
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "ошибка управления ключами").strip()[-500:]
        raise SystemError(detail.removeprefix("altrouter-ssh: "))
    return proc.stdout or ""


def ssh_keys_list(user: str) -> list[dict]:
    keys = []
    for line in _ssh_keys(["key-list", user]).splitlines():
        parts = line.split("|", 2)
        if len(parts) == 3 and parts[0].isdigit():
            keys.append(
                {"index": int(parts[0]), "fingerprint": parts[1], "comment": parts[2].strip()}
            )
    return keys


def ssh_key_add(user: str, key: str) -> str:
    return _ssh_keys(["key-add", user], key.strip()).strip()


def ssh_key_del(user: str, index: int) -> None:
    _ssh_keys(["key-del", user, str(index)])


def updates_count() -> int:
    out = run_checked(["apt-get", "-s", "dist-upgrade"], 120)
    match = re.search(r"^(\d+) upgraded", out, re.M)
    return int(match.group(1)) if match else 0


def updates_apply() -> str:
    out = run_checked(["sudo", "-n", "/usr/bin/apt-get", "update"], 600)
    out += run_checked(["sudo", "-n", "/usr/bin/apt-get", "-y", "dist-upgrade"], 3600)
    return out[-OUTPUT_LIMIT:]


def power(action: str) -> None:
    run_checked(["sudo", "-n", "/usr/bin/systemctl", action], 30)


def tls_paths() -> tuple[Path, Path]:
    base = Path(os.environ.get("ALTROUTER_TLS_DIR", "/opt/altrouter/certs"))
    return base / "altrouter.crt", base / "altrouter.key"


def tls_info(cert_path: Path) -> dict:
    if not cert_path.exists():
        raise SystemError("Файл сертификата не найден")
    try:
        info = ssl._ssl._test_decode_cert(str(cert_path))
    except (OSError, ssl.SSLError) as e:
        raise SystemError(f"Не удалось прочитать сертификат: {e}") from e
    return {
        "subject": info.get("subject"),
        "issuer": info.get("issuer"),
        "not_after": info.get("notAfter"),
    }


def tls_set(cert_pem: str, key_pem: str, cert_path: Path, key_path: Path) -> None:
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    fd_cert, tmp_cert = tempfile.mkstemp(dir=cert_path.parent, suffix=".crt")
    fd_key, tmp_key = tempfile.mkstemp(dir=cert_path.parent, suffix=".key")
    try:
        with os.fdopen(fd_cert, "wb") as f:
            f.write(cert_pem.encode("utf-8"))
        with os.fdopen(fd_key, "wb") as f:
            f.write(key_pem.encode("utf-8"))
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        try:
            ctx.load_cert_chain(tmp_cert, tmp_key)
        except (ssl.SSLError, ValueError, OSError) as e:
            raise SystemError(f"Пара сертификат/ключ не принята: {e}") from e
        os.chmod(tmp_key, 0o600)
        os.replace(tmp_cert, cert_path)
        os.replace(tmp_key, key_path)
    finally:
        for path in (tmp_cert, tmp_key):
            Path(path).unlink(missing_ok=True)


def tls_generate(hosts: list[str], cert_path: Path, key_path: Path) -> None:
    sans = []
    for host in hosts:
        host = host.strip()
        if not host:
            continue
        try:
            sans.append("IP:" + str(ipaddress.ip_address(host)))
        except ValueError:
            if not SAFE_HOST.match(host):
                raise SystemError(f"Некорректный адрес: {host!r}")
            sans.append("DNS:" + host)
    if not sans:
        raise SystemError("Не указан ни один адрес")
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    fd_cert, tmp_cert = tempfile.mkstemp(dir=cert_path.parent, suffix=".crt")
    fd_key, tmp_key = tempfile.mkstemp(dir=cert_path.parent, suffix=".key")
    os.close(fd_cert)
    os.close(fd_key)
    try:
        run_checked(["/usr/bin/openssl", "req", "-x509", "-newkey", "rsa:2048", "-sha256",
                     "-days", "3650", "-nodes", "-keyout", tmp_key, "-out", tmp_cert,
                     "-subj", "/CN=altrouter", "-addext", "subjectAltName=" + ",".join(sans)], 30)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        try:
            ctx.load_cert_chain(tmp_cert, tmp_key)
        except (ssl.SSLError, ValueError, OSError) as e:
            raise SystemError(f"Сгенерированная пара не принята: {e}") from e
        os.chmod(tmp_key, 0o600)
        os.replace(tmp_cert, cert_path)
        os.replace(tmp_key, key_path)
    finally:
        for path in (tmp_cert, tmp_key):
            Path(path).unlink(missing_ok=True)


def backup_pack(config_dir: Path) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name in BACKUP_MEMBERS:
            path = config_dir / name
            if path.exists():
                tar.add(path, arcname=name)
    return buf.getvalue()


def backup_restore(config_dir: Path, data: bytes) -> list[str]:
    restored = []
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            members = {m.name: m for m in tar.getmembers() if m.isfile()}
            unknown = set(members) - set(BACKUP_MEMBERS)
            if unknown:
                raise SystemError("Архив содержит неожиданные файлы: " + ", ".join(sorted(unknown)))
            for name in BACKUP_MEMBERS:
                src = members.get(name)
                if src is None:
                    continue
                stream = tar.extractfile(src)
                if stream is None:
                    continue
                target = config_dir / name
                target.parent.mkdir(parents=True, exist_ok=True)
                _atomic_write(target, stream.read())
                restored.append(name)
    except tarfile.TarError as e:
        raise SystemError(f"Некорректный архив резервной копии: {e}") from e
    return restored


class AccessStore:
    """Настройки доступа к панели (config_dir/access.json)."""

    def __init__(self, config_dir: Path):
        config_dir.mkdir(parents=True, exist_ok=True)
        self.path = config_dir / "access.json"

    def load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        return {}

    def save(self, data: dict) -> None:
        _atomic_write(self.path, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))


def allowed_subnets(iface: str) -> list:
    """IPv4-подсети интерфейса по данным psutil (для ограничения доступа)."""
    nets = []
    for name, addrs in (psutil.net_if_addrs() or {}).items():
        if name != iface:
            continue
        for addr in addrs:
            if addr.family == socket.AF_INET and addr.address and addr.netmask:
                try:
                    network = ipaddress.ip_network(f"{addr.address}/{addr.netmask}", strict=False)
                except ValueError:
                    continue
                nets.append(network)
    return nets
