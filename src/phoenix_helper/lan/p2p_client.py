"""P2P client for connecting to any PHX device (phone or PC).

Uses http.client.HTTPConnection to avoid OpenSSL Applink issues
documented in CLAUDE.md (urllib.request.urlopen crashes with uv Python).
"""
from __future__ import annotations

import http.client
import json
import logging
from pathlib import Path
from typing import Any, Callable

from phoenix_helper.lan.ip_utils import probe_ips

LOGGER = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int], None]  # (received, total)


class P2PClient:
    """Connect to any PHX device as a client."""

    def __init__(
        self,
        hosts: list[str],
        port: int,
        token_prefix: str,
        device_name: str = "PhoenixPC",
    ) -> None:
        self.hosts = hosts
        self.port = port
        self.token_prefix = token_prefix
        self.device_name = device_name
        self._host: str | None = None
        self._token: str | None = None
        self._conn: http.client.HTTPConnection | None = None

    @property
    def is_connected(self) -> bool:
        return self._token is not None

    @property
    def base_host(self) -> str | None:
        return self._host

    def probe_and_connect(self) -> str:
        """Try all hosts, return the reachable one. Raises ConnectionError if none work."""
        if len(self.hosts) == 1:
            reachable = probe_ips(self.hosts, self.port, timeout=3.0)
        else:
            reachable = probe_ips(self.hosts, self.port, timeout=3.0)
        if reachable is None:
            raise ConnectionError(f"None of the hosts are reachable: {self.hosts}")
        self._host = reachable
        self._connect()
        return reachable

    def _connect(self) -> None:
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
        self._conn = http.client.HTTPConnection(
            self._host, self.port, timeout=10
        )

    def _request(
        self,
        method: str,
        path: str,
        body: bytes | dict | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Make an HTTP request and return parsed JSON response."""
        if self._conn is None:
            raise RuntimeError("Not connected. Call probe_and_connect() first.")

        hdrs: dict[str, str] = {"Accept": "application/json"}
        if self._token:
            hdrs["X-Device-Token"] = self._token
        if headers:
            hdrs.update(headers)

        raw_body: bytes | None = None
        if isinstance(body, dict):
            raw_body = json.dumps(body).encode("utf-8")
            hdrs["Content-Type"] = "application/json"
        elif isinstance(body, bytes):
            raw_body = body

        if timeout is not None:
            self._conn.timeout = timeout

        try:
            self._conn.request(method, path, body=raw_body, headers=hdrs)
            resp = self._conn.getresponse()
            data = resp.read()
            if resp.status >= 400:
                try:
                    err = json.loads(data)
                    msg = err.get("message", data.decode(errors="replace"))
                except Exception:
                    msg = data.decode(errors="replace")
                raise RuntimeError(f"HTTP {resp.status}: {msg}")
            return json.loads(data) if data else {}
        except (http.client.RemoteDisconnected, ConnectionError, OSError) as e:
            # Try reconnecting once
            self._connect()
            self._conn.request(method, path, body=raw_body, headers=hdrs)
            resp = self._conn.getresponse()
            data = resp.read()
            if resp.status >= 400:
                raise RuntimeError(f"HTTP {resp.status}: {data.decode(errors='replace')}")
            return json.loads(data) if data else {}

    def register(self, local_name: str = "") -> str:
        """POST /api/register — exchange token prefix for full token."""
        result = self._request("POST", "/api/register", body={
            "token": self.token_prefix,
            "device_name": local_name or self.device_name,
        })
        self._token = result["session"]
        return self._token

    def get_status(self) -> dict[str, Any]:
        """GET /api/status — server capabilities."""
        return self._request("GET", "/api/status")

    def prepare_upload(self, files: dict[str, dict]) -> dict[str, Any]:
        """POST /api/prepare-upload — announce files before transfer.

        Args:
            files: {"file0": {"name": "...", "size": N, "type": "..."}, ...}

        Returns:
            {"sessionId": "...", "fileTokens": {"file0": "tok0", ...}, "expires_in": 600}
        """
        return self._request("POST", "/api/prepare-upload", body={"files": files})

    def upload_file(
        self,
        session_id: str,
        file_id: str,
        file_token: str,
        data: bytes,
        on_progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        """POST /api/upload — transfer raw file bytes."""
        if self._conn is None:
            raise RuntimeError("Not connected")

        import urllib.parse
        path = (
            f"/api/upload?"
            f"sessionId={urllib.parse.quote(session_id)}"
            f"&fileId={urllib.parse.quote(file_id)}"
            f"&token={urllib.parse.quote(file_token)}"
        )

        headers = {
            "Content-Type": "application/octet-stream",
            "Content-Length": str(len(data)),
            "X-Device-Token": self._token or "",
        }

        # Send in chunks with progress
        chunk_size = 65536
        self._conn.timeout = 300  # 5 min for large files
        self._conn.request("POST", path, body=None, headers=headers)

        # Write body manually in chunks
        sent = 0
        total = len(data)
        while sent < total:
            end = min(sent + chunk_size, total)
            self._conn.send(data[sent:end])
            sent = end
            if on_progress:
                on_progress(sent, total)

        resp = self._conn.getresponse()
        resp_data = resp.read()
        if resp.status >= 400:
            raise RuntimeError(f"Upload failed: HTTP {resp.status}")
        return json.loads(resp_data)

    def confirm_seed(
        self,
        session_id: str,
        auto_seed: bool = False,
        title: str = "",
        category: str = "0",
        description: str = "",
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """POST /api/confirm-seed — finalize upload."""
        return self._request("POST", "/api/confirm-seed", body={
            "sessionId": session_id,
            "auto_seed": auto_seed,
            "title": title,
            "category": category,
            "description": description,
            "tags": tags or [],
        })

    def list_files(self) -> list[dict[str, Any]]:
        """GET /api/files — list shared files on the remote device."""
        result = self._request("GET", "/api/files")
        return result.get("entries", [])

    def download_file(
        self,
        remote_path: str,
        save_dir: Path,
        on_progress: ProgressCallback | None = None,
    ) -> Path:
        """GET /api/files/download — download a file from the remote device."""
        if self._conn is None:
            raise RuntimeError("Not connected")

        import urllib.parse
        path = f"/api/files/download?path={urllib.parse.quote(remote_path)}"
        headers = {"X-Device-Token": self._token or ""}
        self._conn.timeout = 600  # 10 min
        self._conn.request("GET", path, headers=headers)

        resp = self._conn.getresponse()
        filename = remote_path.split("/")[-1].split("\\")[-1]
        save_path = save_dir / filename

        total = int(resp.headers.get("Content-Length", 0))
        received = 0
        with open(save_path, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                received += len(chunk)
                if on_progress:
                    on_progress(received, total)

        return save_path

    def disconnect(self) -> None:
        """POST /api/disconnect — graceful disconnect."""
        try:
            self._request("POST", "/api/disconnect")
        except Exception:
            pass

    def close(self) -> None:
        """Close the HTTP connection."""
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
        self._token = None
