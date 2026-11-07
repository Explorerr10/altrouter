from pathlib import Path

from .models import InterfaceConfig

MANAGED_PREFIX = "altrouter-"

HEADER = "# Сгенерировано AltRouter — не редактировать вручную"


def network_file_name(name: str) -> str:
    return f"{MANAGED_PREFIX}{name}.network"


def link_lines(cfg: InterfaceConfig) -> list[str]:
    return ["", "[Link]", f"MACAddress={cfg.mac}"] if cfg.mac else []


def render_network(cfg: InterfaceConfig) -> str:
    lines = [HEADER, "[Match]", f"Name={cfg.name}", *link_lines(cfg), "", "[Network]"]
    if cfg.ipv4 == "dhcp":
        lines.append("DHCP=ipv4")
    if cfg.address:
        lines.append(f"Address={cfg.address}")
    if cfg.gateway:
        lines.append(f"Gateway={cfg.gateway}")
    lines += [f"DNS={server}" for server in cfg.dns]
    if cfg.mtu and cfg.ipv4 != "pppoe":
        lines.append(f"MTUSize={cfg.mtu}")
    if cfg.ipv4 == "dhcp":
        lines += ["", "[DHCP]", "ClientIdentifier=mac"]
    lines.append("")
    return "\n".join(lines)


def write_staging(staging_dir: Path, items: dict[str, InterfaceConfig]) -> None:
    """Атомарно приводит staging-каталог к желаемому набору файлов."""
    staging_dir.mkdir(parents=True, exist_ok=True)
    for path in staging_dir.glob("*.network"):
        path.unlink()
    for cfg in items.values():
        if cfg.role == "off":
            continue
        target = staging_dir / network_file_name(cfg.name)
        tmp = staging_dir / f".{cfg.name}.network.tmp"
        tmp.write_text(render_network(cfg), encoding="utf-8")
        tmp.replace(target)
