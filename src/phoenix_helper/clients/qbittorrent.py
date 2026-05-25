from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import requests

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class QBittorrentConfig:
    webui_url: str = "http://127.0.0.1:8080"
    username: str = "admin"
    password: str = ""


class QBittorrentClientError(RuntimeError):
    pass


class QBittorrentClient:
    def __init__(self, config: QBittorrentConfig, session: requests.Session | None = None) -> None:
        self.config = config
        self.session = session or requests.Session()

    def login(self) -> None:
        resp = self.session.post(
            f"{self.config.webui_url}/api/v2/auth/login",
            data={"username": self.config.username, "password": self.config.password},
            timeout=10,
        )
        if resp.text != "Ok.":
            raise QBittorrentClientError(f"qBittorrent login failed: {resp.text}")
        LOGGER.info("qBittorrent login successful")

    def add_torrent(self, torrent_path: Path, save_path: Path | None = None) -> None:
        torrent_path = torrent_path.expanduser().resolve()

        data = {}
        if save_path is not None:
            data["savepath"] = str(save_path.expanduser().resolve())

        with torrent_path.open("rb") as torrent_file:
            files = {"torrents": (torrent_path.name, torrent_file, "application/x-bittorrent")}
            resp = self.session.post(
                f"{self.config.webui_url}/api/v2/torrents/add",
                data=data,
                files=files,
                timeout=30,
            )

        if resp.status_code != 200 or resp.text != "Ok.":
            raise QBittorrentClientError(f"qBittorrent add torrent failed: {resp.text}")
        LOGGER.info("qBittorrent torrent added: %s", torrent_path.name)

    def check_connection(self) -> None:
        self.login()
        resp = self.session.get(f"{self.config.webui_url}/api/v2/app/version", timeout=10)
        if resp.status_code != 200:
            raise QBittorrentClientError(f"qBittorrent API error: {resp.status_code}")
        LOGGER.info("qBittorrent version: %s", resp.text)
