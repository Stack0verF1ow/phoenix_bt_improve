from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class AppConfig:
    site_base_url: str = "http://phoenix.stu.edu.cn"
    upload_path: str = "/BT/upload.aspx"
    tracker_url: str = ""
    username: str = ""
    password: str = ""
    cookie_header: str = ""
    utorrent_executable: str = ""
    utorrent_webui_url: str = "http://127.0.0.1:8080/gui/"
    utorrent_webui_username: str = ""
    utorrent_webui_password: str = ""
    temp_dir: Path = Path(".cache/phoenix-helper")
    generated_torrent_dir: Path = Path("torrents/generated")
    final_torrent_dir: Path = Path("torrents/final")

    @property
    def upload_url(self) -> str:
        return self.site_base_url.rstrip("/") + self.upload_path

    def ensure_directories(self) -> None:
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.generated_torrent_dir.mkdir(parents=True, exist_ok=True)
        self.final_torrent_dir.mkdir(parents=True, exist_ok=True)


SAVED_CONFIG_VERSION = 1
SENSITIVE_FIELDS = {"password", "cookie_header", "utorrent_webui_password"}


def user_config_dir() -> Path:
    if sys.platform == "win32":
        root = Path.home() / "AppData" / "Roaming"
    else:
        root = Path.home() / ".config"
    return root / "PhoenixHelper"


def user_config_path() -> Path:
    return user_config_dir() / "config.json"


def load_app_config(path: Path | None = None) -> AppConfig:
    config_path = path or user_config_path()
    config = AppConfig()
    if not config_path.exists():
        return config

    data = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return config

    values = data.get("values", {})
    if isinstance(values, dict):
        for name, value in values.items():
            if hasattr(config, name):
                setattr(config, name, _deserialize_value(name, value))

    secrets = data.get("secrets", {})
    if isinstance(secrets, dict):
        for name, value in secrets.items():
            if hasattr(config, name) and isinstance(value, str):
                setattr(config, name, _unprotect_text(value))
    return config


def save_app_config(config: AppConfig, path: Path | None = None) -> Path:
    config_path = path or user_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    values: dict[str, Any] = {}
    secrets: dict[str, str] = {}
    for name in config.__dataclass_fields__:
        value = getattr(config, name)
        if name in SENSITIVE_FIELDS:
            if value:
                secrets[name] = _protect_text(str(value))
            continue
        values[name] = _serialize_value(value)

    payload = {
        "version": SAVED_CONFIG_VERSION,
        "values": values,
        "secrets": secrets,
    }
    config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return config_path


def _serialize_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    return value


def _deserialize_value(name: str, value: Any) -> Any:
    if name.endswith("_dir") or name == "temp_dir":
        return Path(str(value))
    return value


def _protect_text(text: str) -> str:
    data = text.encode("utf-8")
    if sys.platform != "win32":
        return "plain:" + base64.b64encode(data).decode("ascii")
    return "dpapi:" + base64.b64encode(_crypt_protect_data(data)).decode("ascii")


def _unprotect_text(value: str) -> str:
    if value.startswith("plain:"):
        return base64.b64decode(value.removeprefix("plain:")).decode("utf-8")
    if value.startswith("dpapi:"):
        protected = base64.b64decode(value.removeprefix("dpapi:"))
        return _crypt_unprotect_data(protected).decode("utf-8")
    return value


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _crypt_protect_data(data: bytes) -> bytes:
    blob_in, _buffer = _bytes_to_blob(data)
    blob_out = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = ctypes.wintypes.BOOL
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(blob_in),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(blob_out),
    ):
        raise ctypes.WinError()
    return _blob_to_bytes_and_free(blob_out)


def _crypt_unprotect_data(data: bytes) -> bytes:
    blob_in, _buffer = _bytes_to_blob(data)
    blob_out = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.POINTER(ctypes.wintypes.LPWSTR),
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = ctypes.wintypes.BOOL
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(blob_out),
    ):
        raise ctypes.WinError()
    return _blob_to_bytes_and_free(blob_out)


def _bytes_to_blob(data: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
    buffer = ctypes.create_string_buffer(data)
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


def _blob_to_bytes_and_free(blob: _DataBlob) -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        kernel32 = ctypes.windll.kernel32
        kernel32.LocalFree.argtypes = [ctypes.wintypes.HLOCAL]
        kernel32.LocalFree.restype = ctypes.wintypes.HLOCAL
        kernel32.LocalFree(ctypes.cast(blob.pbData, ctypes.wintypes.HLOCAL))
