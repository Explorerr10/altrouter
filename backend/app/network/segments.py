"""Модели этапа 3: сегменты (мосты LAN + DHCP), статические маршруты, политики WAN."""

import ipaddress
import re

from pydantic import BaseModel, Field, field_validator, model_validator

from .models import NAME_RE

MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")
SEGMENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,8}$")
HOSTNAME_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,61}[A-Za-z0-9])?$")


def _parse_ipv4(value: str, what: str) -> str:
    try:
        addr = ipaddress.ip_address(value)
    except ValueError as e:
        raise ValueError(f"Некорректный {what}: {value!r}") from e
    if addr.version != 4:
        raise ValueError(f"{what.capitalize()} должен быть IPv4-адресом")
    return str(addr)


class Reservation(BaseModel):
    """Постоянная привязка IP↔MAC (резервирование адреса DHCP-клиента)."""

    mac: str
    ip: str
    hostname: str | None = None
    comment: str | None = None

    @field_validator("mac", mode="before")
    @classmethod
    def _clean_mac(cls, value):
        if value is None:
            return None
        value = str(value).strip().lower().replace("-", ":")
        return value or None

    @field_validator("ip", mode="before")
    @classmethod
    def _strip_ip(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("hostname", "comment", mode="before")
    @classmethod
    def _strip_optionals(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @model_validator(mode="after")
    def _check(self) -> "Reservation":
        if not MAC_RE.match(self.mac or ""):
            raise ValueError(f"Некорректный MAC-адрес: {self.mac!r}")
        self.ip = _parse_ipv4(self.ip, "IP-адрес")
        if self.hostname and not HOSTNAME_RE.match(self.hostname):
            raise ValueError(f"Недопустимое имя хоста: {self.hostname!r}")
        if self.comment and len(self.comment) > 64:
            raise ValueError("Комментарий длиннее 64 символов")
        return self


class DhcpSettings(BaseModel):
    """Настройки DHCP-сервера на сегменте."""

    enabled: bool = False
    pool_start: str | None = None
    pool_end: str | None = None
    lease_hours: int = 12
    dns: list[str] = []

    @field_validator("pool_start", "pool_end", mode="before")
    @classmethod
    def _strip_pool(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("dns", mode="before")
    @classmethod
    def _clean_dns(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            value = value.replace(";", ",").split(",")
        if not isinstance(value, list):
            raise ValueError("Список DNS-серверов должен быть массивом")
        return [str(item).strip() for item in value if str(item).strip()]

    @field_validator("lease_hours", mode="before")
    @classmethod
    def _empty_number_to_default(cls, value):
        if value is None or value == "":
            return 12
        return value

    @model_validator(mode="after")
    def _check(self) -> "DhcpSettings":
        if not (1 <= self.lease_hours <= 8760):
            raise ValueError("Срок аренды — от 1 до 8760 часов")
        cleaned_dns = []
        for server in self.dns:
            cleaned_dns.append(_parse_ipv4(server, "DNS-сервер"))
        self.dns = cleaned_dns
        return self


class SegmentConfig(BaseModel):
    """LAN-сегмент: подсеть на мосту из одного или нескольких LAN-портов."""

    id: str
    name: str
    interfaces: list[str] = []
    address: str
    dhcp: DhcpSettings = Field(default_factory=DhcpSettings)
    reservations: list[Reservation] = []

    @field_validator("id", "name", "address", mode="before")
    @classmethod
    def _strip_strings(cls, value):
        if isinstance(value, str):
            return value.strip()
        return value

    @model_validator(mode="after")
    def _check(self) -> "SegmentConfig":
        if not SEGMENT_ID_RE.match(self.id or ""):
            raise ValueError(
                "Идентификатор — латиница в нижнем регистре, цифры и дефис, до 9 символов"
            )
        if not self.name or len(self.name) > 64:
            raise ValueError("Название сегмента — от 1 до 64 символов")
        if not self.interfaces:
            raise ValueError("Укажите хотя бы один LAN-порт сегмента")
        for port in self.interfaces:
            if not NAME_RE.match(port):
                raise ValueError(f"Недопустимое имя интерфейса: {port!r}")
        if len(set(self.interfaces)) != len(self.interfaces):
            raise ValueError("Порты в сегменте не должны повторяться")

        try:
            iface = ipaddress.ip_interface(self.address)
        except ValueError as e:
            raise ValueError(
                f"Некорректный адрес сегмента {self.address!r} (например, 192.168.10.1/24)"
            ) from e
        if iface.version != 4:
            raise ValueError("Адрес сегмента должен быть IPv4")
        self.address = str(iface)
        network = iface.network

        if self.dhcp.enabled:
            if not self.dhcp.pool_start or not self.dhcp.pool_end:
                raise ValueError("Для DHCP задайте границы пула адресов")
            start = ipaddress.ip_address(_parse_ipv4(self.dhcp.pool_start, "начало пула"))
            end = ipaddress.ip_address(_parse_ipv4(self.dhcp.pool_end, "конец пула"))
            for addr, what in ((start, "начало"), (end, "конец")):
                if addr not in network:
                    raise ValueError(f"{what.capitalize()} пула вне подсети сегмента")
            if start >= end:
                raise ValueError("Начало пула должно быть меньше конца")
            for addr in (network.network_address, network.broadcast_address, iface.ip):
                if start <= addr <= end:
                    raise ValueError(
                        "Пул не должен включать адрес сети, широковещательный и адрес роутера"
                    )

        seen_macs: set[str] = set()
        seen_ips: set[str] = set()
        for res in self.reservations:
            if res.mac in seen_macs:
                raise ValueError(f"MAC {res.mac} встречается в резервах дважды")
            if res.ip in seen_ips:
                raise ValueError(f"IP {res.ip} назначен в резервах дважды")
            seen_macs.add(res.mac)
            seen_ips.add(res.ip)
            if ipaddress.ip_address(res.ip) not in network:
                raise ValueError(f"IP {res.ip} вне подсети сегмента")
        return self


class StaticRoute(BaseModel):
    """Статический маршрут (networkd [Route])."""

    dest: str
    gateway: str
    iface: str | None = None
    metric: int | None = None

    @field_validator("dest", "gateway", mode="before")
    @classmethod
    def _strip_strings(cls, value):
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("iface", "metric", mode="before")
    @classmethod
    def _empty_to_none(cls, value):
        if value is None or value == "":
            return None
        return value

    @model_validator(mode="after")
    def _check(self) -> "StaticRoute":
        try:
            net = ipaddress.ip_network(self.dest, strict=False)
        except ValueError as e:
            raise ValueError(
                f"Некорректная подсеть назначения {self.dest!r} (например, 10.5.0.0/16)"
            ) from e
        if net.version != 4:
            raise ValueError("Назначение должно быть IPv4-подсетью")
        self.dest = str(net)
        self.gateway = _parse_ipv4(self.gateway, "шлюз")
        if self.iface and not NAME_RE.match(self.iface):
            raise ValueError(f"Недопустимое имя интерфейса: {self.iface!r}")
        if self.metric is not None and not (1 <= self.metric <= 10000):
            raise ValueError("Метрика — от 1 до 10000")
        return self


class PingCheck(BaseModel):
    """Периодическая проверка доступности через WAN-подключение."""

    enabled: bool = False
    target: str = "1.1.1.1"
    interval_s: int = 30
    fail_threshold: int = 3

    @field_validator("target", mode="before")
    @classmethod
    def _strip_target(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("interval_s", mode="before")
    @classmethod
    def _empty_interval(cls, value):
        if value is None or value == "":
            return 30
        return value

    @field_validator("fail_threshold", mode="before")
    @classmethod
    def _empty_threshold(cls, value):
        if value is None or value == "":
            return 3
        return value

    @model_validator(mode="after")
    def _check(self) -> "PingCheck":
        if not self.target:
            self.target = "1.1.1.1"
        try:
            ipaddress.ip_address(self.target)
        except ValueError:
            if not HOSTNAME_RE.match(self.target):
                raise ValueError(f"Некорректная цель проверки: {self.target!r}") from None
        if not (5 <= self.interval_s <= 3600):
            raise ValueError("Интервал проверки — от 5 до 3600 секунд")
        if not (1 <= self.fail_threshold <= 20):
            raise ValueError("Порог неудач — от 1 до 20")
        return self


class WanPolicy(BaseModel):
    """Политика одного WAN-подключения: приоритет и Ping Check."""

    priority: int | None = None
    ping_check: PingCheck = Field(default_factory=PingCheck)
    weight: int = 1

    @field_validator("priority", mode="before")
    @classmethod
    def _empty_to_none(cls, value):
        if value is None or value == "":
            return None
        return value

    @field_validator("weight", mode="before")
    @classmethod
    def _empty_weight(cls, value):
        if value is None or value == "":
            return 1
        return value

    @model_validator(mode="after")
    def _check(self) -> "WanPolicy":
        if self.priority is not None and not (1 <= self.priority <= 99):
            raise ValueError("Приоритет — от 1 (главный) до 99")
        if not (1 <= self.weight <= 100):
            raise ValueError("Вес — от 1 до 100")
        return self

    @property
    def route_metric(self) -> int | None:
        return self.priority * 100 if self.priority else None


class WanConfig(BaseModel):
    """Политики всех WAN-подключений."""

    policies: dict[str, WanPolicy] = Field(default_factory=dict)
    mode: str = "failover"

    @field_validator("mode", mode="before")
    @classmethod
    def _default_mode(cls, value):
        return value or "failover"

    @model_validator(mode="after")
    def _check(self) -> "WanConfig":
        if self.mode not in ("failover", "balance"):
            raise ValueError("Режим WAN — failover или balance")
        for iface in self.policies:
            if not NAME_RE.match(iface):
                raise ValueError(f"Недопустимое имя интерфейса: {iface!r}")
        return self

    def metric_for(self, iface: str) -> int | None:
        policy = self.policies.get(iface)
        return policy.route_metric if policy else None
