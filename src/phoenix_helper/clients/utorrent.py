from __future__ import annotations

import base64
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import requests


@dataclass(frozen=True, slots=True)
class UTorrentConfig:
    executable: str = ""
    webui_url: str = "http://127.0.0.1:8080/gui/"
    username: str = ""
    password: str = ""


class UTorrentClientError(RuntimeError):
    pass


class UTorrentClient:
    def __init__(self, config: UTorrentConfig, session: requests.Session | None = None) -> None:
        self.config = config
        self.session = session or requests.Session()
        if config.username or config.password:
            self.session.auth = (config.username, config.password)

    def open_torrent(self, torrent_path: Path) -> None:
        torrent_path = torrent_path.expanduser().resolve()
        if self.config.executable:
            subprocess.Popen([self.config.executable, str(torrent_path)])
            return
        subprocess.Popen([str(torrent_path)], shell=True)

    def add_torrent_via_webui(self, torrent_path: Path, save_path: Path | None = None) -> None:
        token = self._get_token()
        params = {"action": "add-file", "token": token}
        if save_path is not None:
            params["download_dir"] = str(save_path.expanduser().resolve())

        with torrent_path.expanduser().resolve().open("rb") as torrent_file:
            files = {"torrent_file": (torrent_path.name, torrent_file, "application/x-bittorrent")}
            response = self.session.post(self._url(""), params=params, files=files, timeout=30)
        if response.status_code >= 400:
            raise UTorrentClientError(f"µTorrent WebUI add-file failed: HTTP {response.status_code}")

    def check_webui(self) -> None:
        self._get_token()

    def _get_token(self) -> str:
        response = self.session.get(self._url("token.html"), timeout=10)
        response.raise_for_status()
        marker_start = response.text.find("<div id='token' style='display:none;'>")
        if marker_start == -1:
            marker_start = response.text.find('<div id="token" style="display:none;">')
        if marker_start == -1:
            raise UTorrentClientError("µTorrent WebUI token not found")
        start = response.text.find(">", marker_start) + 1
        end = response.text.find("</div>", start)
        if end == -1:
            raise UTorrentClientError("µTorrent WebUI token is malformed")
        return response.text[start:end].strip()

    def _url(self, path: str) -> str:
        return urljoin(self.config.webui_url.rstrip("/") + "/", path)
