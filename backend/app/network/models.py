import ipaddress
import re

from pydantic import BaseModel, field_validator, model_validator

NAME_RE = re.compile(r"^[a-zA-Z0-9._-]{1,15}$")

MAC_RE = re.compile(r"^([0-9a-f]{2}:){5}[0-9a-f]{2}$")

ROLES = ("wan", "lan", "off")


class InterfaceConfig(BaseModel):
    """Желаемая конфигурация одного физического интерфейса."""

    name: str
    role: str
    ipv4: str | None = None
    address: str | None = None
    gateway: str | None = None
    dns: list[str] = []
    mtu: int | None = None
    vlan_id: int | None = None
    mac: str | None = None
    pppoe_username: str | None = None
    pppoe_password: str | None = None

    @field_validator(
        "ipv4", "address", "gateway", "mac", "pppoe_username", "pppoe_password", mode="before"
    )
    @classmethod
    def _strip_optionals(cls, value):
        if value is None:
            return None
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

    @field_validator("mtu", "vlan_id", mode="before")
    @classmethod
    def _empty_number_to_none(cls, value):
        if value is None or value == "":
            return None
        return value

    @model_validator(mode="after")
    def _check_semantics(self) -> "InterfaceConfig":
        if self.name == "lo":
            raise ValueError("Интерфейс lo не настраивается")
        if not NAME_RE.match(self.name):
            raise ValueError(f"Недопустимое имя интерфейса: {self.name!r}")
        if self.role not in ROLES:
            raise ValueError("Роль должна быть одной из: wan, lan, off")

        if self.role == "off":
            if (
                self.ipv4 or self.address or self.gateway or self.dns or self.mtu or self.mac
                or self.pppoe_username or self.pppoe_password
            ):
                raise ValueError("Для выключенного интерфейса никакие параметры не задаются")
            return self

        if self.mac:
            if self.role != "wan":
                raise ValueError("MAC задаётся только для WAN-подключений")
            self.mac = self.mac.lower()
            if not MAC_RE.match(self.mac):
                raise ValueError("Некорректный MAC-адрес, ожидается формат AA:BB:CC:DD:EE:FF")

        if self.mtu is not None and not (68 <= self.mtu <= 65535):
            raise ValueError("MTU должен быть в диапазоне 68–65535")
        if self.vlan_id is not None and not (1 <= self.vlan_id <= 4094):
            raise ValueError("VLAN ID должен быть в диапазоне 1–4094")

        if not self.ipv4:
            raise ValueError("Укажите способ настройки IPv4: dhcp, static или pppoe")
        if self.ipv4 not in ("dhcp", "static", "pppoe"):
            raise ValueError("Способ настройки IPv4 должен быть dhcp, static или pppoe")
        if self.ipv4 == "pppoe":
            if self.role != "wan":
                raise ValueError("PPPoE настраивается только для WAN-подключений")
            if not self.pppoe_username:
                raise ValueError("Укажите логин PPPoE")
            if self.address or self.gateway:
                raise ValueError("При PPPoE адрес и шлюз не задаются")
            for value in (self.pppoe_username, self.pppoe_password):
                if value and re.search(r'["\\\r\n]', value):
                    raise ValueError(
                        "Логин и пароль PPPoE не должны содержать кавычек, "
                        "обратных слешей и переводов строк"
                    )
        if self.role == "lan" and self.ipv4 != "static":
            raise ValueError("LAN-порт требует статического адреса")

        if self.ipv4 == "dhcp":
            if self.address or self.gateway:
                raise ValueError("При DHCP адрес и шлюз не задаются")
        elif self.ipv4 == "static":
            if not self.address:
                raise ValueError("Укажите адрес с префиксом подсети, например 192.168.10.1/24")
            if "/" not in self.address:
                raise ValueError("Адрес должен включать префикс подсети, например 192.168.10.1/24")
            try:
                iface = ipaddress.ip_interface(self.address)
            except ValueError as e:
                raise ValueError(f"Некорректный адрес {self.address!r}") from e
            if iface.version != 4:
                raise ValueError("Адрес должен быть IPv4")
            self.address = str(iface)

        if self.role == "lan":
            if self.gateway:
                raise ValueError("Для LAN-порта шлюз не задаётся")
            if self.dns:
                raise ValueError("DNS-серверы задаются только для WAN-подключений")
        elif self.ipv4 == "static":
            if not self.gateway:
                raise ValueError("Укажите шлюз для статического WAN-подключения")
            try:
                gateway = ipaddress.ip_address(self.gateway)
            except ValueError as e:
                raise ValueError(f"Некорректный шлюз {self.gateway!r}") from e
            if gateway.version != 4:
                raise ValueError("Шлюз должен быть IPv4-адресом")
            if gateway not in ipaddress.ip_interface(self.address).network:
                raise ValueError("Шлюз должен находиться в той же подсети, что и адрес")

        cleaned_dns = []
        for server in self.dns:
            try:
                parsed = ipaddress.ip_address(server)
            except ValueError as e:
                raise ValueError(f"Некорректный DNS-сервер {server!r}") from e
            if parsed.version != 4:
                raise ValueError(f"DNS-сервер {server!r} должен быть IPv4-адресом")
            cleaned_dns.append(str(parsed))
        self.dns = cleaned_dns

        return self
