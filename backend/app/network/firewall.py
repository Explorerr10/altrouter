"""Модели этапа 4: правила файрвола, переадресация портов (DNAT), локальные DNS-имена."""

import ipaddress
import re

from pydantic import BaseModel, field_validator, model_validator

from .models import NAME_RE
from .segments import HOSTNAME_RE, SEGMENT_ID_RE, _parse_ipv4

DIRECTIONS = ("forward", "input")
ZONES = ("wan", "lan")
RULE_PROTOS = ("any", "tcp", "udp")
FORWARD_PROTOS = ("tcp", "udp", "both")
ACTIONS = ("allow", "drop")

PORT_SPEC_RE = re.compile(r"^\d{1,5}(-\d{1,5})?$")


def is_zone(value: str) -> bool:
    """Зона правила: фиксированная (wan, lan) или идентификатор сегмента."""
    return value in ZONES or bool(SEGMENT_ID_RE.match(value))


def parse_port_spec(value: str, what: str) -> str:
    """Порт или диапазон портов вида 8000-9000 (границы включительно)."""
    if not PORT_SPEC_RE.match(value or ""):
        raise ValueError(f"Некорректный {what}: {value!r} (порт или диапазон вида 8000-9000)")
    bounds = [int(part) for part in value.split("-")]
    for port in bounds:
        if not (1 <= port <= 65535):
            raise ValueError(f"{what.capitalize()} должен быть от 1 до 65535")
    if len(bounds) == 2 and bounds[0] >= bounds[1]:
        raise ValueError("Начало диапазона портов должно быть меньше конца")
    return value


def port_range_size(spec: str) -> int:
    parts = [int(part) for part in spec.split("-")]
    return parts[1] - parts[0] + 1 if len(parts) == 2 else 1


def _parse_ipv4_net(value: str, what: str) -> str:
    """IPv4-адрес или подсеть; возвращает каноническую строку."""
    if "/" in value:
        try:
            net = ipaddress.ip_network(value, strict=False)
        except ValueError as e:
            raise ValueError(f"Некорректная подсеть {what}: {value!r}") from e
        if net.version != 4:
            raise ValueError(f"{what.capitalize()} должен быть IPv4")
        return str(net)
    return _parse_ipv4(value, what)


class FirewallRule(BaseModel):
    """Правило файрвола для трафика «из зоны»: между зонами (forward) или к роутеру (input)."""

    direction: str = "forward"
    zone: str = "wan"
    proto: str = "any"
    src_ip: str | None = None
    src_port: str | None = None
    dst_ip: str | None = None
    dst_port: str | None = None
    action: str = "allow"
    comment: str | None = None

    @field_validator("direction", "zone", "proto", "action", mode="before")
    @classmethod
    def _strip_strings(cls, value):
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("src_ip", "src_port", "dst_ip", "dst_port", "comment", mode="before")
    @classmethod
    def _strip_optionals(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @model_validator(mode="after")
    def _check(self) -> "FirewallRule":
        if self.direction not in DIRECTIONS:
            raise ValueError(
                "Направление правила — «forward» (между зонами) или «input» (к роутеру), "
                f"а не {self.direction!r}"
            )
        if not is_zone(self.zone):
            raise ValueError(
                f"Недопустимая зона правила: {self.zone!r} (wan, lan или идентификатор сегмента)"
            )
        if self.proto not in RULE_PROTOS:
            raise ValueError(f"Протокол правила — «any», «tcp» или «udp», а не {self.proto!r}")
        if self.action not in ACTIONS:
            raise ValueError(f"Действие правила — «allow» или «drop», а не {self.action!r}")
        if self.src_ip:
            self.src_ip = _parse_ipv4_net(self.src_ip, "адреса источника")
        if self.dst_ip:
            self.dst_ip = _parse_ipv4_net(self.dst_ip, "адреса приёмника")
        if self.src_port:
            self.src_port = parse_port_spec(self.src_port, "порт источника")
        if self.dst_port:
            self.dst_port = parse_port_spec(self.dst_port, "порт приёмника")
        if self.proto == "any" and (self.src_port or self.dst_port):
            raise ValueError("Порты указываются только для протоколов tcp или udp")
        if self.comment and len(self.comment) > 64:
            raise ValueError("Комментарий длиннее 64 символов")
        return self


class PortForward(BaseModel):
    """Переадресация порта (DNAT) с WAN-подключения на устройство локальной сети."""

    wan: str | None = None
    proto: str = "tcp"
    port: str
    to_ip: str
    to_port: str | None = None
    comment: str | None = None

    @field_validator("proto", mode="before")
    @classmethod
    def _strip_proto(cls, value):
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("port", "to_ip", mode="before")
    @classmethod
    def _strip_required(cls, value):
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("wan", "to_port", "comment", mode="before")
    @classmethod
    def _strip_optionals(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @model_validator(mode="after")
    def _check(self) -> "PortForward":
        if self.wan and not NAME_RE.match(self.wan):
            raise ValueError(f"Недопустимое имя интерфейса: {self.wan!r}")
        if self.proto not in FORWARD_PROTOS:
            raise ValueError(f"Протокол переадресации — «tcp», «udp» или «both», а не {self.proto!r}")
        self.port = parse_port_spec(self.port, "внешний порт")
        self.to_ip = _parse_ipv4(self.to_ip, "адрес назначения")
        if self.to_port:
            self.to_port = parse_port_spec(self.to_port, "порт назначения")
            if port_range_size(self.port) != port_range_size(self.to_port):
                raise ValueError(
                    "Диапазон портов назначения должен совпадать по размеру с внешним диапазоном"
                )
        if self.comment and len(self.comment) > 64:
            raise ValueError("Комментарий длиннее 64 символов")
        return self


class DnsRecord(BaseModel):
    """Локальная DNS-запись (dnsmasq host-record): имя устройства в домашней сети."""

    hostname: str
    ip: str
    comment: str | None = None

    @field_validator("hostname", "ip", mode="before")
    @classmethod
    def _strip_required(cls, value):
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("comment", mode="before")
    @classmethod
    def _strip_optionals(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @model_validator(mode="after")
    def _check(self) -> "DnsRecord":
        if not HOSTNAME_RE.match(self.hostname):
            raise ValueError(f"Недопустимое имя хоста: {self.hostname!r}")
        self.ip = _parse_ipv4(self.ip, "IP-адрес")
        if self.comment and len(self.comment) > 64:
            raise ValueError("Комментарий длиннее 64 символов")
        return self
