"""Read uTorrent settings.dat to auto-detect WebUI configuration."""
from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from phoenix_helper.torrent.bencode import BencodeError, decode

LOGGER = logging.getLogger(__name__)


@dataclass
class UTorrentSettings:
    """Parsed WebUI settings from settings.dat."""
    settings_path: Path | None = None
    webui_enabled: bool = False
    webui_port: int = 8080
    webui_username: str = ""
    webui_has_password: bool = False
    webui_hashword: bytes = b""
    webui_salt: str = ""


def find_settings_dat() -> Path | None:
    """Locate uTorrent settings.dat on disk."""
    candidates = [
        Path(os.environ.get("APPDATA", "")) / "uTorrent" / "settings.dat",
        Path(os.environ.get("LOCALAPPDATA", "")) / "uTorrent" / "settings.dat",
        Path.home() / "AppData" / "Roaming" / "uTorrent" / "settings.dat",
    ]
    for p in candidates:
        if p.exists():
            return p.resolve()
    return None


def read_utorrent_settings(path: Path | None = None) -> UTorrentSettings:
    """Parse uTorrent settings.dat and extract WebUI configuration."""
    if path is None:
        path = find_settings_dat()
    if path is None or not path.exists():
        LOGGER.warning("settings.dat not found")
        return UTorrentSettings()

    data = path.read_bytes()
    try:
        decoded = decode(data)
    except BencodeError as e:
        LOGGER.warning("Failed to parse settings.dat: %s", e)
        return UTorrentSettings(settings_path=path)

    if not isinstance(decoded, dict):
        LOGGER.warning("Unexpected settings.dat format")
        return UTorrentSettings(settings_path=path)

    raw: dict[bytes, Any] = decoded

    def d(key: str) -> Any:
        return raw.get(key.encode("utf-8"))

    settings = UTorrentSettings(settings_path=path)

    # WebUI enabled
    enabled = d("webui.enable")
    if isinstance(enabled, int):
        settings.webui_enabled = bool(enabled)

    # Port
    port = d("webui.port")
    if isinstance(port, int) and port > 0:
        settings.webui_port = port

    # Username
    username = d("webui.username")
    if isinstance(username, bytes):
        settings.webui_username = username.decode("utf-8", errors="replace")

    # Password hash
    hashword = d("webui.hashword")
    if isinstance(hashword, bytes) and hashword:
        settings.webui_has_password = True
        settings.webui_hashword = hashword

    # Salt
    salt = d("webui.salt")
    if isinstance(salt, bytes):
        settings.webui_salt = salt.decode("utf-8", errors="replace")

    LOGGER.info(
        "uTorrent WebUI: enabled=%s, port=%d, username=%r, has_password=%s",
        settings.webui_enabled, settings.webui_port,
        settings.webui_username or "(none)", settings.webui_has_password,
    )
    return settings


def build_webui_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/gui/"


def verify_password(password: str, salt: str, stored_hash: bytes) -> bool:
    """Check if a password matches the stored hash from settings.dat."""
    hasher = hashlib.sha1()
    hasher.update(password.encode("utf-8"))
    hasher.update(salt.encode("utf-8"))
    return hasher.digest() == stored_hash
