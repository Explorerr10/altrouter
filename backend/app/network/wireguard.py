"""Модели этапа 5: WireGuard-интерфейсы, пиры, ключи, статус туннелей, клиентский конфиг."""

import ipaddress
import re
import subprocess

from pydantic import BaseModel, field_validator, model_validator

from .firewall import _parse_ipv4_net
from .segments import SEGMENT_ID_RE

KEY_RE = re.compile(r"^[A-Za-z0-9+/]{43}=$")
ROUTE_MODES = ("none", "all", "devices")
WG_NAME_PREFIX = "arwg-"
ENDPOINT_RE = re.compile(r"^(?P<host>[^\s:]+|\[[0-9a-fA-F:]+\])(?::(?P<port>\d{1,5}))?$")


def iface_name(wg_id: str) -> str:
    return f"{WG_NAME_PREFIX}{wg_id}"


def _parse_key(value: str | None, what: str) -> str | None:
    if value is None:
        return None
    if not KEY_RE.match(value):
        raise ValueError(f"Некорректный {what} (44 символа base64, как у wg genkey)")
    return value


def _parse_endpoint(value: str, what: str) -> str:
    match = ENDPOINT_RE.match(value)
    if not match or (match.group("port") and not (1 <= int(match.group("port")) <= 65535)):
        raise ValueError(f"Некорректный {what}: {value!r} (хост или хост:порт)")
    return value


def parse_allowed_ip(value: str, what: str) -> str:
    """IPv4 или подсеть; возвращает каноническую строку (хост-адрес → /32)."""
    return _parse_ipv4_net(value if "/" in value else f"{value}/32", what)


class WireguardPeer(BaseModel):
    """Пир туннеля: клиент снаружи или соседняя сеть."""

    name: str
    public_key: str | None = None
    private_key: str | None = None
    allowed_ips: list[str] = []
    preshared_key: str | None = None
    endpoint: str | None = None
    keepalive: int | None = None
    comment: str | None = None

    @field_validator("name", mode="before")
    @classmethod
    def _clean_name(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator(
        "public_key", "private_key", "preshared_key", "endpoint", "comment", mode="before"
    )
    @classmethod
    def _strip_optionals(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("keepalive", mode="before")
    @classmethod
    def _empty_to_none(cls, value):
        if value is None or value == "":
            return None
        return value

    @model_validator(mode="after")
    def _check(self) -> "WireguardPeer":
        if not self.name or len(self.name) > 64:
            raise ValueError("Имя пира — от 1 до 64 символов")
        self.public_key = _parse_key(self.public_key, "публичный ключ пира")
        self.private_key = _parse_key(self.private_key, "приватный ключ пира")
        self.preshared_key = _parse_key(self.preshared_key, "preshared key")
        if not self.public_key and not self.private_key:
            raise ValueError(
                f"Пир «{self.name}»: укажите публичный ключ или сгенерируйте пару ключей"
            )
        if not self.allowed_ips:
            raise ValueError(f"Пир «{self.name}»: укажите хотя бы одну Allowed IP")
        self.allowed_ips = [
            parse_allowed_ip(item, f"Allowed IP пира «{self.name}»") for item in self.allowed_ips
        ]
        if len(set(self.allowed_ips)) != len(self.allowed_ips):
            raise ValueError(f"Пир «{self.name}»: Allowed IP повторяются")
        if self.endpoint:
            self.endpoint = _parse_endpoint(self.endpoint, "адрес пира")
        if self.keepalive is not None and not (1 <= self.keepalive <= 3600):
            raise ValueError("Persistent keepalive — от 1 до 3600 секунд")
        if self.comment and len(self.comment) > 64:
            raise ValueError("Комментарий длиннее 64 символов")
        return self


class WireguardInterface(BaseModel):
    """WireGuard-туннель: UDP-порт, адрес в туннеле, пиры и режим маршрутизации."""

    id: str
    name: str
    enabled: bool = True
    address: str
    listen_port: int
    private_key: str | None = None
    public_key: str | None = None
    route_mode: str = "none"
    priority: int | None = None
    devices: list[str] = []
    endpoint: str | None = None
    mtu: int | None = None
    peers: list[WireguardPeer] = []

    @field_validator("id", "name", "address", mode="before")
    @classmethod
    def _strip_strings(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("endpoint", "private_key", "public_key", mode="before")
    @classmethod
    def _strip_optionals(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("listen_port", "mtu", "priority", mode="before")
    @classmethod
    def _empty_to_none(cls, value):
        if value is None or value == "":
            return None
        return value

    @model_validator(mode="after")
    def _check(self) -> "WireguardInterface":
        if not SEGMENT_ID_RE.match(self.id or ""):
            raise ValueError(
                "Идентификатор — латиница в нижнем регистре, цифры и дефис, до 9 символов"
            )
        if not self.name or len(self.name) > 64:
            raise ValueError("Название туннеля — от 1 до 64 символов")
        try:
            iface = ipaddress.ip_interface(self.address)
        except ValueError as e:
            raise ValueError(
                f"Некорректный адрес туннеля {self.address!r} (например, 10.9.0.1/24)"
            ) from e
        if iface.version != 4:
            raise ValueError("Адрес туннеля должен быть IPv4")
        self.address = str(iface)
        if not (1 <= self.listen_port <= 65535):
            raise ValueError("Порт прослушивания — от 1 до 65535")
        self.private_key = _parse_key(self.private_key, "приватный ключ туннеля")
        self.public_key = _parse_key(self.public_key, "публичный ключ туннеля")
        if self.route_mode not in ROUTE_MODES:
            raise ValueError(
                "Режим маршрутизации — «none» (без маршрутов), «all» (весь трафик) "
                f"или «devices» (выбранные устройства), а не {self.route_mode!r}"
            )
        if self.route_mode == "all" and not (1 <= (self.priority or 0) <= 99):
            raise ValueError("Для режима «весь трафик» задайте приоритет от 1 до 99")
        self.priority = self.priority if 1 <= (self.priority or 0) <= 99 else None
        if self.route_mode != "devices":
            self.devices = []
        else:
            self.devices = [
                _parse_ipv4_net(item if "/" in item else f"{item}/32", "адрес устройства")
                for item in self.devices
            ]
            if not self.devices:
                raise ValueError("Для режима «выбранные устройства» укажите хотя бы один адрес")
        if self.endpoint:
            self.endpoint = _parse_endpoint(self.endpoint, "адрес туннеля (для клиентов)")
        if self.mtu is not None and not (1280 <= self.mtu <= 9000):
            raise ValueError("MTU — от 1280 до 9000")

        seen_keys: set[str] = set()
        seen_ips: set[str] = set()
        for peer in self.peers:
            if peer.public_key and peer.public_key in seen_keys:
                raise ValueError(f"Публичный ключ пира «{peer.name}» уже используется")
            if peer.public_key:
                seen_keys.add(peer.public_key)
            for subnet in peer.allowed_ips:
                if subnet in seen_ips:
                    raise ValueError(
                        f"Allowed IP {subnet} у пира «{peer.name}» уже назначен другому пиру"
                    )
                seen_ips.add(subnet)
        return self

    @property
    def network(self) -> ipaddress.IPv4Network:
        return ipaddress.ip_interface(self.address).network

    @property
    def table_id(self) -> int:
        """Номер таблицы маршрутизации и fwmark для policy routing (= порт, уникален)."""
        return self.listen_port


def generate_keypair() -> tuple[str, str]:
    """Пара ключей через wireguard-tools (без привилегий)."""
    try:
        proc = subprocess.run(["wg", "genkey"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeError("Не удалось вызвать wg genkey (wireguard-tools)") from e
    if proc.returncode != 0:
        raise RuntimeError(f"wg genkey завершился с ошибкой: {(proc.stderr or '').strip()}")
    private = proc.stdout.strip()
    return private, derive_public(private)


def derive_public(private: str) -> str:
    try:
        proc = subprocess.run(
            ["wg", "pubkey"], input=private + "\n", capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeError("Не удалось вызвать wg pubkey (wireguard-tools)") from e
    if proc.returncode != 0:
        raise RuntimeError(f"wg pubkey завершился с ошибкой: {(proc.stderr or '').strip()}")
    return proc.stdout.strip()


def wg_status(command: str = "sudo -n /usr/bin/wg show all dump") -> dict:
    """Разбор `wg show all dump`; при любой неудаче — пустой статус (панель не должна падать)."""
    try:
        proc = subprocess.run(
            command.split(), capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if proc.returncode != 0:
        return {}
    items: dict[str, dict] = {}
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        # peer-строка: iface, public-key, psk, endpoint, allowed-ips, handshake, rx, tx, keepalive
        if len(parts) < 8 or parts[0] == "interface":
            continue
        name, pub, _psk, endpoint, _allowed, handshake, rx, tx, *_ = parts
        peers = items.setdefault(name, {"peers": {}})
        peers["peers"][pub] = {
            "endpoint": None if endpoint == "(none)" else endpoint,
            "handshake": int(handshake) if handshake.isdigit() else 0,
            "rx": int(rx) if rx.isdigit() else 0,
            "tx": int(tx) if tx.isdigit() else 0,
        }
    return items


def render_client_config(iface: WireguardInterface, peer: WireguardPeer) -> str:
    """Клиентский конфиг для экспорта (файл .conf и QR-код)."""
    if not peer.private_key:
        raise ValueError(
            f"Пир «{peer.name}»: ключи генерируются на клиенте, конфиг для экспорта недоступен"
        )
    if not iface.public_key:
        raise ValueError(f"Туннель «{iface.name}»: нет публичного ключа сервера")
    lines = [
        "# Сгенерировано AltRouter — клиентский конфиг WireGuard",
        "[Interface]",
        f"PrivateKey = {peer.private_key}",
        f"Address = {', '.join(peer.allowed_ips)}",
    ]
    if iface.mtu:
        lines.append(f"MTU = {iface.mtu}")
    lines += ["", "[Peer]", f"PublicKey = {iface.public_key}"]
    if iface.endpoint:
        lines.append(f"Endpoint = {iface.endpoint}:{iface.listen_port}"
                     if ":" not in iface.endpoint else f"Endpoint = {iface.endpoint}")
    lines += ["AllowedIPs = 0.0.0.0/0", "PersistentKeepalive = 25"]
    return "\n".join(lines) + "\n"
