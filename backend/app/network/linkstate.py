"""Up/down физического интерфейса через sudo-хелпер altrouter-ifstate."""

import re
import subprocess

HELPER = "/usr/local/sbin/altrouter-ifstate"
SAFE_IFACE = re.compile(r"^[A-Za-z0-9._-]{1,15}$")


class LinkError(RuntimeError):
    pass


def link_set(name: str, up: bool) -> None:
    if not SAFE_IFACE.fullmatch(name):
        raise LinkError(f"некорректное имя интерфейса: {name!r}")
    action = "up" if up else "down"
    try:
        subprocess.run(
            ["sudo", "-n", HELPER, action, name],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError as e:
        raise LinkError(f"хелпер не найден: {HELPER}") from e
    except subprocess.TimeoutExpired as e:
        raise LinkError("истекло время ожидания команды ip link") from e
    except subprocess.CalledProcessError as e:
        detail = (e.stderr or e.stdout or "").strip() or f"ip link set {action} завершился с ошибкой"
        raise LinkError(detail) from e
