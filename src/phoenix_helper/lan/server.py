"""LAN HTTP server for mobile-PC file transfer.

Inspired by LocalSend's REST API design — split upload into
prepare + transfer + confirm three-step model for robustness.

API Endpoints
-------------
POST /api/register       — exchange QR token for full session
GET  /api/status         — PC capabilities and status
POST /api/prepare-upload — announce files, get session+file tokens
POST /api/upload         — transfer raw file bytes
POST /api/confirm-seed   — mark upload complete, trigger optional seeding
GET  /api/upload/<sid>   — poll upload and seeding status
POST /api/cancel         — cancel an upload session
GET  /api/files          — list files available for download
GET  /api/files/download — stream a file for download
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
import threading
import time
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Callable

from phoenix_helper.config import AppConfig
from phoenix_helper.lan.file_store import FileStore
from phoenix_helper.lan.ip_utils import get_lan_ips

LOGGER = logging.getLogger(__name__)

# ── rate limiter ──────────────────────────────────────────────────

_RATE_LIMIT_WINDOW = 60.0  # seconds
_RATE_LIMIT_MAX = 30        # requests per window per IP


class _RateLimiter:
    """Simple in-memory token-bucket rate limiter per IP."""

    def __init__(self) -> None:
        self._buckets: dict[str, list[float]] = {}

    def allow(self, ip: str) -> bool:
        now = time.monotonic()
        window_start = now - _RATE_LIMIT_WINDOW
        hits = [t for t in self._buckets.get(ip, []) if t > window_start]
        if len(hits) >= _RATE_LIMIT_MAX:
            return False
        hits.append(now)
        self._buckets[ip] = hits
        return True


# ── session manager ───────────────────────────────────────────────

_SESSION_TTL = 600.0  # seconds — sessions expire after 10 min


class _ConnectedDevice:
    __slots__ = ("ip", "name", "connected_at", "last_seen")

    def __init__(self, ip: str, name: str = "") -> None:
        self.ip = ip
        self.name = name
        self.connected_at = time.monotonic()
        self.last_seen = time.monotonic()


class _DeviceRegistry:
    """Tracks devices that have completed registration."""

    def __init__(self) -> None:
        self._devices: dict[str, _ConnectedDevice] = {}  # ip -> device
        self._lock = threading.Lock()

    def register(self, ip: str, name: str = "") -> None:
        with self._lock:
            if ip in self._devices:
                self._devices[ip].last_seen = time.monotonic()
                if name:
                    self._devices[ip].name = name
            else:
                self._devices[ip] = _ConnectedDevice(ip, name)

    def unregister(self, ip: str) -> None:
        with self._lock:
            self._devices.pop(ip, None)

    def list_devices(self) -> list[dict]:
        now = time.monotonic()
        with self._lock:
            # Remove stale entries (no activity for 60s)
            stale = [ip for ip, d in self._devices.items()
                     if now - d.last_seen > 60.0]
            for ip in stale:
                del self._devices[ip]
            return [
                {
                    "ip": d.ip,
                    "name": d.name or d.ip,
                    "connected_at": round(d.connected_at),
                }
                for d in self._devices.values()
            ]


class _Session:
    __slots__ = ("id", "files", "file_ids", "file_tokens", "received",
                 "seed_data", "seed_status", "created_at", "peer_ip")

    def __init__(self, sid: str, peer_ip: str) -> None:
        self.id = sid
        self.files: dict[str, dict] = {}         # fileId -> {name, size, type}
        self.file_ids: list[str] = []
        self.file_tokens: dict[str, str] = {}     # fileId -> token (for upload validation)
        self.received: dict[str, bytes] = {}      # fileId -> data
        self.seed_data: dict | None = None        # {title, category, …}
        self.seed_status: str = "idle"            # idle|seeding|done|error
        self.created_at = time.monotonic()
        self.peer_ip = peer_ip


class _SessionManager:
    """Manages upload sessions with auto-expiry."""

    def __init__(self) -> None:
        self._sessions: dict[str, _Session] = {}
        self._lock = threading.Lock()
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()

    def create(self, peer_ip: str) -> _Session:
        sid = str(uuid.uuid4())
        with self._lock:
            self._sessions[sid] = _Session(sid, peer_ip)
        return self._sessions[sid]

    def get(self, sid: str) -> _Session | None:
        with self._lock:
            s = self._sessions.get(sid)
            if s and time.monotonic() - s.created_at < _SESSION_TTL:
                return s
            if s:
                del self._sessions[sid]
        return None

    def remove(self, sid: str) -> None:
        with self._lock:
            self._sessions.pop(sid, None)

    def _cleanup_loop(self) -> None:
        while True:
            time.sleep(60)
            now = time.monotonic()
            with self._lock:
                expired = [sid for sid, s in self._sessions.items()
                           if now - s.created_at >= _SESSION_TTL]
                for sid in expired:
                    del self._sessions[sid]


# ── request handler ───────────────────────────────────────────────

class LanRequestHandler(BaseHTTPRequestHandler):
    """Handles all LAN API requests.

    Shared state injected as class attributes before server starts.
    """

    config: AppConfig = None
    file_store: FileStore = None
    qr_token: str = ""          # the 6-char prefix from QR code
    full_token: str = ""        # the full SHA256 token
    on_seed_ready: Callable | None = None
    server_ref: "LanServer | None" = None
    _limiter: _RateLimiter = _RateLimiter()
    _sessions: _SessionManager = _SessionManager()
    _devices: _DeviceRegistry = _DeviceRegistry()
    _serve_dirs: list[Path] | None = None

    # ── helpers ───────────────────────────────────────────────

    def log_message(self, fmt: str, *args: Any) -> None:
        LOGGER.info("LAN: %s", fmt % args)

    @property
    def _client_ip(self) -> str:
        return self.client_address[0]

    def _send_json(self, status: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status: int, msg: str) -> None:
        self._send_json(status, {"status": "error", "message": msg})

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length)

    def _check_auth(self) -> bool:
        """Return True if authenticated. Sends 403 and returns False otherwise."""
        token = self.headers.get("X-Device-Token", "")
        if token == self.full_token or token == self.qr_token:
            return True
        self._send_error(403, "Invalid or missing X-Device-Token")
        return False

    def _check_rate(self) -> bool:
        if self._limiter.allow(self._client_ip):
            return True
        self._send_error(429, "Too many requests")
        return False

    def _check_auth_and_rate(self) -> bool:
        return self._check_rate() and self._check_auth()

    # ── routing ────────────────────────────────────────────────

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Device-Token")
        self.end_headers()

    def do_GET(self) -> None:
        path = self.clean_path
        if path == "/api/status":
            self._handle_status()
        elif path == "/api/devices":
            self._handle_list_devices()
        elif path == "/api/files":
            self._handle_list_files()
        elif path.startswith("/api/files/download"):
            self._handle_download()
        elif path.startswith("/api/upload/"):
            parts = path.split("/")
            if len(parts) == 4:
                self._handle_upload_status(parts[3])
            else:
                self._send_error(404, "Not found")
        else:
            self._send_error(404, "Not found")

    def do_POST(self) -> None:
        path = self.clean_path
        if path == "/api/register":
            self._handle_register()
        elif path == "/api/prepare-upload":
            self._handle_prepare_upload()
        elif path == "/api/upload":
            self._handle_upload()
        elif path == "/api/confirm-seed":
            self._handle_confirm_seed()
        elif path == "/api/cancel":
            self._handle_cancel()
        else:
            self._send_error(404, "Not found")

    # ── endpoint implementations ───────────────────────────────

    def _handle_register(self) -> None:
        """POST /api/register — exchange QR token for full session."""
        if not self._check_rate():
            return
        try:
            data = json.loads(self._read_body())
        except Exception:
            self._send_error(400, "Invalid JSON")
            return
        if data.get("token") != self.qr_token:
            self._send_error(403, "Invalid token")
            return
        device_name = data.get("device_name", "")
        self._devices.register(self._client_ip, device_name)
        LOGGER.info("Device '%s' registered from %s", device_name or "?", self._client_ip)
        if self.server_ref and self.server_ref.on_device_connected:
            self.server_ref.on_device_connected(self._client_ip, device_name)
        self._send_json(200, {
            "status": "ok",
            "session": self.full_token,
            "device_name": self.config.device_name or socket.gethostname(),
        })

    def _handle_status(self) -> None:
        """GET /api/status — return PC capabilities."""
        if not self._check_auth_and_rate():
            return
        try:
            from phoenix_helper.clients.discovery import find_utorrent_executable
            ut_avail = find_utorrent_executable() is not None
        except Exception:
            ut_avail = False
        self._send_json(200, {
            "name": self.config.device_name or socket.gethostname(),
            "version": "0.2.0",
            "protocol_version": 1,
            "utorrent_available": ut_avail,
            "phoenix_logged_in": bool(self.config.cookie_header),
            "files_available": len(self._serve_dirs or []),
            "max_upload_size": 10 * 1024 * 1024 * 1024,  # 10 GB hint
        })

    def _handle_prepare_upload(self) -> None:
        """POST /api/prepare-upload — announce files before transfer.

        Request: {
            "files": {
                "file0": {"name": "photo.jpg", "size": 524288, "type": "image/jpeg"},
                "file1": {"name": "doc.pdf", "size": 1048576, "type": "application/pdf"}
            }
        }
        Response: {
            "sessionId": "uuid",
            "fileTokens": {"file0": "tok0", "file1": "tok1"},
            "expires_in": 600
        }
        """
        if not self._check_auth_and_rate():
            return
        try:
            body = json.loads(self._read_body())
        except Exception:
            self._send_error(400, "Invalid JSON")
            return

        files = body.get("files", {})
        if not files or not isinstance(files, dict):
            self._send_error(400, "Missing or invalid 'files' object")
            return

        session = self._sessions.create(self._client_ip)
        for fid, finfo in files.items():
            session.files[fid] = {
                "name": finfo.get("name", "unknown"),
                "size": int(finfo.get("size", 0)),
                "type": finfo.get("type", "application/octet-stream"),
            }
            session.file_ids.append(fid)
            tok = hashlib.sha256(os.urandom(16)).hexdigest()[:12]
            session.file_tokens[fid] = tok

        LOGGER.info("Session %s prepared with %d files from %s",
                    session.id, len(files), self._client_ip)
        self._send_json(200, {
            "sessionId": session.id,
            "fileTokens": session.file_tokens,
            "expires_in": int(_SESSION_TTL),
        })

    def _handle_upload(self) -> None:
        """POST /api/upload?sessionId=<sid>&fileId=<fid>&token=<tok>

        Body: raw file bytes (application/octet-stream)
        """
        if not self._check_auth_and_rate():
            return

        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        sid = (qs.get("sessionId") or [None])[0]
        fid = (qs.get("fileId") or [None])[0]
        token = (qs.get("token") or [None])[0]

        if not sid or not fid or not token:
            self._send_error(400, "Missing sessionId, fileId, or token")
            return

        session = self._sessions.get(sid)
        if not session:
            self._send_error(404, "Session not found or expired")
            return

        finfo = session.files.get(fid)
        if not finfo:
            self._send_error(404, f"File '{fid}' not in session")
            return

        expected_token = session.file_tokens.get(fid)
        if not expected_token or token != expected_token:
            self._send_error(403, "Invalid file token")
            return

        file_data = self._read_body()
        session.received[fid] = file_data
        LOGGER.info("Session %s received file '%s' (%d bytes)",
                    sid, finfo["name"], len(file_data))

        # Store in memory only — actual persistence happens at confirm-seed
        self._send_json(200, {
            "status": "received",
            "fileId": fid,
            "name": finfo["name"],
            "size": len(file_data),
        })

    def _handle_confirm_seed(self) -> None:
        """POST /api/confirm-seed — finalize upload, optionally start seeding.

        Request: {
            "sessionId": "uuid",
            "auto_seed": true,
            "title": "Resource Title",
            "category": "1",
            "description": "...",
            "tags": ["tag1", "tag2"]
        }
        Response: {
            "status": "seeding" | "idle",
            "uploads": [{"uploadId": "...", "name": "...", "size": 123}]
        }
        """
        if not self._check_auth_and_rate():
            return
        try:
            body = json.loads(self._read_body())
        except Exception:
            self._send_error(400, "Invalid JSON")
            return

        sid = body.get("sessionId", "")
        session = self._sessions.get(sid)
        if not session:
            self._send_error(404, "Session not found or expired")
            return

        auto_seed = body.get("auto_seed", False)
        uploads_info = []

        for fid in session.file_ids:
            file_data = session.received.get(fid)
            if file_data is None:
                continue
            # Persist to disk now
            upload_id = self.file_store.create_upload(
                session.files[fid]["name"], file_data
            )
            uploads_info.append({
                "uploadId": upload_id,
                "name": session.files[fid]["name"],
                "size": len(file_data),
            })

            if self.server_ref and self.server_ref.on_file_received:
                self.server_ref.on_file_received(upload_id, session.files[fid]["name"])

            # Trigger auto-seed for the last file (single-title granularity)
            if auto_seed and self.on_seed_ready and fid == session.file_ids[-1]:
                t = threading.Thread(
                    target=self.on_seed_ready,
                    args=(
                        upload_id,
                        body.get("title", ""),
                        body.get("category", "0"),
                        body.get("description", ""),
                        body.get("tags", []),
                    ),
                    daemon=True,
                )
                t.start()
                session.seed_status = "seeding"

        self._sessions.remove(sid)
        self._send_json(200, {
            "status": "seeding" if auto_seed else "idle",
            "uploads": uploads_info,
        })

    def _handle_upload_status(self, sid: str) -> None:
        """GET /api/upload/<sid> — poll session status."""
        if not self._check_auth_and_rate():
            return
        session = self._sessions.get(sid)
        if not session:
            self._send_json(200, {"sessionId": sid, "status": "expired"})
            return
        received_count = len(session.received)
        total_count = len(session.file_ids)
        self._send_json(200, {
            "sessionId": sid,
            "status": "active",
            "files_received": received_count,
            "files_total": total_count,
            "seed_status": session.seed_status,
            "received": [
                {"fileId": fid, "name": session.files[fid]["name"],
                 "size": len(session.received.get(fid, b""))}
                for fid in session.file_ids if fid in session.received
            ],
        })

    def _handle_cancel(self) -> None:
        """POST /api/cancel — cancel an upload session."""
        if not self._check_rate():
            return
        try:
            body = json.loads(self._read_body())
        except Exception:
            self._send_error(400, "Invalid JSON")
            return
        sid = body.get("sessionId", "")
        self._sessions.remove(sid)
        LOGGER.info("Session %s cancelled by peer", sid)
        self._send_json(200, {"status": "cancelled"})

    def _handle_list_devices(self) -> None:
        """GET /api/devices — list currently connected devices."""
        self._send_json(200, {"devices": self._devices.list_devices(),
                              "count": len(self._devices._devices)})

    def _handle_list_files(self) -> None:
        """GET /api/files — list files in served directories."""
        if not self._check_auth_and_rate():
            return
        entries: list[dict] = []
        dirs = self._serve_dirs or _DEFAULT_SERVE_DIRS()
        for sd in dirs:
            if not sd.exists():
                continue
            for entry in sorted(sd.iterdir())[:300]:
                if entry.name.startswith("."):
                    continue
                try:
                    st = entry.stat()
                except OSError:
                    continue
                entries.append({
                    "path": str(entry),
                    "name": entry.name,
                    "type": "dir" if entry.is_dir() else "file",
                    "size": st.st_size if entry.is_file() else 0,
                    "mtime": st.st_mtime,
                })
        entries.sort(key=lambda e: (e["type"] != "dir", e["name"].lower()))
        self._send_json(200, {"entries": entries})

    def _handle_download(self) -> None:
        """GET /api/files/download?path=<urlencoded_path>"""
        if not self._check_auth_and_rate():
            return
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        file_path_str = (qs.get("path") or [None])[0]
        if not file_path_str:
            self._send_error(400, "Missing 'path' query parameter")
            return

        file_path = Path(file_path_str)
        if not file_path.exists() or not file_path.is_file():
            self._send_error(404, "File not found")
            return

        try:
            file_size = file_path.stat().st_size
        except OSError:
            self._send_error(500, "Cannot access file")
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition",
                         f'attachment; filename="{file_path.name}"')
        self.send_header("Content-Length", str(file_size))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (ConnectionError, BrokenPipeError):
                    break

    @property
    def clean_path(self) -> str:
        """Return the URL path without query string, trailing slash removed."""
        return self.path.split("?")[0].rstrip("/")


def _DEFAULT_SERVE_DIRS() -> list[Path]:
    return [
        Path.home() / "Downloads",
        Path.home() / "Desktop",
        Path.home() / "Documents",
    ]


# ── server lifecycle ──────────────────────────────────────────────

class LanServer:
    """Manages the LAN HTTP server lifecycle on a background thread."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.file_store = FileStore(config.upload_receive_dir)
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.on_seed_ready: Callable | None = None
        self.on_file_received: Callable | None = None
        self.on_device_connected: Callable | None = None
        self.serve_dirs: list[Path] | None = None
        self._full_token: str = ""

    @property
    def is_running(self) -> bool:
        return self._server is not None

    @property
    def qr_token(self) -> str:
        return self._full_token[:6]

    @property
    def full_token(self) -> str:
        return self._full_token

    def start(self, port: int = 18080, serve_dirs: list[Path] | None = None) -> int:
        if self._server:
            raise RuntimeError("Server already running")

        self._full_token = hashlib.sha256(os.urandom(32)).hexdigest()
        self.serve_dirs = serve_dirs

        LanRequestHandler.config = self.config
        LanRequestHandler.file_store = self.file_store
        LanRequestHandler.qr_token = self.qr_token
        LanRequestHandler.full_token = self._full_token
        LanRequestHandler.on_seed_ready = self.on_seed_ready
        LanRequestHandler.server_ref = self
        LanRequestHandler._serve_dirs = self.serve_dirs

        self._server = HTTPServer(("0.0.0.0", port), LanRequestHandler)
        actual_port = self._server.server_port
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        LOGGER.info("LAN server started on 0.0.0.0:%d", actual_port)
        LOGGER.info("QR token: %s", self.qr_token)
        return actual_port

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server = None
            self._thread = None
            self._full_token = ""
            LOGGER.info("LAN server stopped")

    @property
    def listen_port(self) -> int:
        return self._server.server_port if self._server else 0

    def get_qr_content(self) -> str:
        from phoenix_helper.lan.qr_generator import build_qr_content
        ips = get_lan_ips()
        if not ips:
            ips = ["127.0.0.1"]
        device_name = self.config.device_name or socket.gethostname()
        return build_qr_content("pc", device_name, ips, self.listen_port, self._full_token)
