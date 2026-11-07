import os
from pathlib import Path

APP_VERSION = "0.8.0"


def default_config_dir() -> Path:
    return Path(os.environ.get("ALTROUTER_CONFIG_DIR", "/etc/altrouter"))


def management_iface() -> str:
    return os.environ.get("ALTROUTER_MGMT_IFACE", "")
