from __future__ import annotations

import logging
from pathlib import Path


_LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format=_LOG_FORMAT,
    )
    # Also write to a file for diagnostics
    log_path = Path.cwd() / "phx_desktop_debug.log"
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(logging.Formatter(_LOG_FORMAT))
    logging.getLogger().addHandler(fh)


def redact(value: str, visible: int = 4) -> str:
    if not value:
        return ""
    if len(value) <= visible:
        return "*" * len(value)
    return value[:visible] + "*" * (len(value) - visible)
