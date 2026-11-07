import os


def _getloadavg() -> list[float]:
    getloadavg = getattr(os, "getloadavg", None)
    if getloadavg is None:
        return []
    try:
        return [round(x, 2) for x in getloadavg()]
    except (NotImplementedError, OSError):
        return []
