"""Read cookies from installed browsers (Edge/Chrome)."""
from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import json
import sqlite3
import tempfile
import shutil
from pathlib import Path

PHOENIX_HOST = "phoenix.stu.edu.cn"


def read_browser_cookies(host: str = PHOENIX_HOST) -> str:
    """Read cookies from Edge or Chrome for the given host. Returns cookie header string."""
    for browser_name, cookie_db_path in _find_cookie_dbs():
        try:
            cookies = _read_cookies_from_db(cookie_db_path, host)
            if cookies:
                return "; ".join(f"{name}={value}" for name, value in cookies)
        except Exception:
            continue
    return ""


def _find_cookie_dbs() -> list[tuple[str, Path]]:
    """Find cookie databases for installed browsers."""
    results = []
    local_app_data = Path.home() / "AppData" / "Local"

    # Edge
    edge_db = local_app_data / "Microsoft" / "Edge" / "User Data" / "Default" / "Network" / "Cookies"
    if edge_db.exists():
        results.append(("Edge", edge_db))
    edge_db_alt = local_app_data / "Microsoft" / "Edge" / "User Data" / "Default" / "Cookies"
    if edge_db_alt.exists():
        results.append(("Edge", edge_db_alt))

    # Chrome
    chrome_db = local_app_data / "Google" / "Chrome" / "User Data" / "Default" / "Network" / "Cookies"
    if chrome_db.exists():
        results.append(("Chrome", chrome_db))
    chrome_db_alt = local_app_data / "Google" / "Chrome" / "User Data" / "Default" / "Cookies"
    if chrome_db_alt.exists():
        results.append(("Chrome", chrome_db_alt))

    return results


def _read_cookies_from_db(db_path: Path, host: str) -> list[tuple[str, str]]:
    """Read and decrypt cookies from a Chromium cookie database."""
    # Copy the DB to avoid lock issues
    tmp_dir = Path(tempfile.mkdtemp())
    try:
        tmp_db = tmp_dir / "Cookies"
        shutil.copy2(db_path, tmp_db)

        conn = sqlite3.connect(str(tmp_db))
        cursor = conn.cursor()

        # Try the new schema first (encrypted_value)
        try:
            cursor.execute(
                "SELECT name, encrypted_value, value FROM cookies WHERE host_key LIKE ?",
                (f"%{host}%",),
            )
        except sqlite3.OperationalError:
            # Try older schema
            cursor.execute(
                "SELECT name, encrypted_value FROM cookies WHERE host_key LIKE ?",
                (f"%{host}%",),
            )

        cookies = []
        for row in cursor.fetchall():
            name = row[0]
            encrypted_value = row[1]
            plain_value = row[2] if len(row) > 2 else ""

            if plain_value:
                cookies.append((name, plain_value))
            elif encrypted_value:
                try:
                    decrypted = _decrypt_chromium_cookie(encrypted_value)
                    if decrypted:
                        cookies.append((name, decrypted))
                except Exception:
                    pass

        conn.close()
        return cookies
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _decrypt_chromium_cookie(encrypted_value: bytes) -> str:
    """Decrypt a Chromium-encrypted cookie value using DPAPI."""
    if not encrypted_value:
        return ""

    # v10/v11 encryption prefix
    if encrypted_value[:3] == b'v10' or encrypted_value[:3] == b'v11':
        encrypted_value = encrypted_value[3:]

    return _dpapi_decrypt(encrypted_value).decode("utf-8", errors="replace")


def _dpapi_decrypt(data: bytes) -> bytes:
    """Decrypt data using Windows DPAPI."""
    class DataBlob(ctypes.Structure):
        _fields_ = [
            ("cbData", ctypes.wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    buffer = ctypes.create_string_buffer(data)
    blob_in = DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    blob_out = DataBlob()

    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        raise ctypes.WinError()

    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32 = ctypes.windll.kernel32
        kernel32.LocalFree(ctypes.cast(blob_out.pbData, ctypes.wintypes.HLOCAL))


def get_edge_user_data_dir() -> Path | None:
    """Get the Edge user data directory for Selenium."""
    local_app_data = Path.home() / "AppData" / "Local"
    edge_dir = local_app_data / "Microsoft" / "Edge" / "User Data"
    return edge_dir if edge_dir.exists() else None


def get_chrome_user_data_dir() -> Path | None:
    """Get the Chrome user data directory for Selenium."""
    local_app_data = Path.home() / "AppData" / "Local"
    chrome_dir = local_app_data / "Google" / "Chrome" / "User Data"
    return chrome_dir if chrome_dir.exists() else None
