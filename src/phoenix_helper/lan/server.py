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

import json
import logging
import secrets
import socket
import threading
import time
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Callable

from phoenix_helper.config import AppConfig
from phoenix_helper.lan.chunk_store import ChunkStore
from phoenix_helper.lan.file_store import FileStore
from phoenix_helper.lan.ip_utils import get_lan_ips

LOGGER = logging.getLogger(__name__)

# ── rate limiter ──────────────────────────────────────────────────

_RATE_LIMIT_WINDOW = 60.0  # seconds
_RATE_LIMIT_MAX = 60        # requests per window per IP


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
        self.connected_at = time.time()
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

    def touch(self, ip: str) -> None:
        """Refresh last_seen for a device (called on each authenticated request)."""
        with self._lock:
            d = self._devices.get(ip)
            if d:
                d.last_seen = time.monotonic()

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
                 "seed_data", "seed_status", "created_at", "peer_ip",
                 "chunked_files")

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
        self.chunked_files: set[str] = set()


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
                    s = self._sessions.get(sid)
                    if s and hasattr(s, 'chunked_files') and s.chunked_files:
                        cs = getattr(LanRequestHandler, 'chunk_store', None)
                        if cs:
                            cs.cleanup_session(sid)
                    del self._sessions[sid]


# ── request handler ───────────────────────────────────────────────

class LanRequestHandler(BaseHTTPRequestHandler):
    """Handles all LAN API requests.

    Shared state injected as class attributes before server starts.
    """

    config: AppConfig = None
    file_store: FileStore = None
    chunk_store: ChunkStore = None
    qr_token: str = ""          # the 6-char prefix from QR code
    full_token: str = ""        # the full SHA256 token
    on_seed_ready: Callable | None = None
    on_file_downloaded: Callable | None = None
    on_download_progress: Callable | None = None
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

    def _read_body_chunked(self, chunk_size: int = 65536,
                           on_chunk: Callable[[int, int], None] | None = None) -> bytes:
        """Read body in chunks, calling on_chunk(received_so_far, total) after each."""
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return b""
        if on_chunk is None:
            return self.rfile.read(length)
        buf = bytearray()
        received = 0
        while received < length:
            to_read = min(chunk_size, length - received)
            chunk = self.rfile.read(to_read)
            if not chunk:
                break
            buf.extend(chunk)
            received += len(chunk)
            on_chunk(received, length)
        return bytes(buf)

    def _check_auth(self) -> bool:
        """Return True if authenticated. Sends 403 and returns False otherwise."""
        token = self.headers.get("X-Device-Token", "")
        if token == self.full_token or token == self.qr_token:
            self._devices.touch(self._client_ip)
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
        elif path == "/api/ping":
            self._handle_ping()
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
        elif path == "/api/disconnect":
            self._handle_disconnect()
        else:
            self._send_error(404, "Not found")

    # ── endpoint implementations ───────────────────────────────

    def _handle_ping(self) -> None:
        """GET /api/ping — unauthenticated liveness probe for IP discovery."""
        self._send_json(200, {"status": "ok"})

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
            "device_type": "pc",
            "can_auto_seed": True,
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
        resp_chunk_size: int | None = None
        for fid, finfo in files.items():
            chunk_size = int(finfo.get("chunkSize", 0)) or None
            session.files[fid] = {
                "name": finfo.get("name", "unknown"),
                "size": int(finfo.get("size", 0)),
                "type": finfo.get("type", "application/octet-stream"),
            }
            if chunk_size:
                session.files[fid]["chunkSize"] = chunk_size
            session.file_ids.append(fid)
            tok = secrets.token_hex(6)  # 12 hex chars
            session.file_tokens[fid] = tok
            if chunk_size:
                session.chunked_files.add(fid)
                self.chunk_store.prepare_file(
                    session_id=session.id,
                    file_id=fid,
                    file_name=finfo.get("name", "unknown"),
                    file_size=int(finfo.get("size", 0)),
                    file_type=finfo.get("type", "application/octet-stream"),
                    file_token=tok,
                    chunk_size=chunk_size,
                )
                resp_chunk_size = chunk_size

        LOGGER.info("Session %s prepared with %d files from %s",
                    session.id, len(files), self._client_ip)
        self._send_json(200, {
            "sessionId": session.id,
            "fileTokens": session.file_tokens,
            "chunkSize": resp_chunk_size or self.chunk_store.chunk_size,
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
        chunk_index_str = (qs.get("chunkIndex") or [None])[0]
        chunk_hash = (qs.get("chunkHash") or [None])[0]
        chunk_index = int(chunk_index_str) if chunk_index_str is not None else None

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

        # ── chunked upload path ──
        if fid in session.chunked_files and chunk_index is not None:
            file_data = self._read_body()
            try:
                result = self.chunk_store.write_chunk(
                    session_id=sid,
                    file_id=fid,
                    chunk_index=chunk_index,
                    data=file_data,
                    expected_crc32=chunk_hash,
                )
            except FileNotFoundError:
                self._send_error(404, "Session or file meta not found")
                return

            if result["status"] == "checksum_mismatch":
                self._send_json(400, {
                    "status": "error",
                    "message": "CRC32 checksum mismatch",
                    "computedCrc32": result["computedCrc32"],
                    "chunkIndex": chunk_index,
                })
                return

            if result["status"] == "duplicate":
                self._send_json(409, {
                    "status": "duplicate",
                    "fileId": fid,
                    "chunkIndex": chunk_index,
                    "chunksReceived": result["chunksReceived"],
                    "totalChunks": result["totalChunks"],
                })
                return

            if self.server_ref and self.server_ref.on_upload_progress:
                finfo = session.files[fid]
                total_chunks = result["totalChunks"]
                if total_chunks > 0:
                    progress = len(result["chunksReceived"]) / total_chunks
                    self.server_ref.on_upload_progress(
                        finfo["name"], int(progress * finfo["size"]),
                        finfo["size"],
                        len(session.received) + len(session.chunked_files),
                        len(session.file_ids),
                    )

            self._send_json(200, {
                "status": "chunk_received",
                "fileId": fid,
                "chunkIndex": chunk_index,
                "chunksReceived": result["chunksReceived"],
                "totalChunks": result["totalChunks"],
            })
            return

        # ── legacy whole-file upload path ──

        content_length = int(self.headers.get("Content-Length", 0))
        if content_length <= 0:
            self._send_error(411, "Missing or zero Content-Length")
            return

        def _on_chunk(received: int, total: int) -> None:
            if self.server_ref and self.server_ref.on_upload_progress:
                self.server_ref.on_upload_progress(
                    finfo["name"], received, total,
                    len(session.received), len(session.file_ids)
                )

        try:
            file_data = self._read_body_chunked(on_chunk=_on_chunk)
        except (ConnectionError, OSError) as exc:
            LOGGER.warning("Upload body read failed for session %s file '%s': %s",
                           sid, fid, exc)
            self._send_error(400, "Connection lost during upload")
            return

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
        file_hashes = body.get("fileHashes") or {}
        uploads_info = []

        for fid in session.file_ids:
            finfo = session.files[fid]

            if fid in session.chunked_files:
                file_hash = file_hashes.get(fid)
                final_path = self.chunk_store.finalize_file(
                    session_id=sid,
                    file_id=fid,
                    expected_sha256=file_hash,
                )
                if final_path is None:
                    self._send_json(400, {
                        "status": "error",
                        "message": f"File '{fid}' incomplete or integrity check failed",
                    })
                    return
                file_size = final_path.stat().st_size
                upload_id = str(uuid.uuid4())
                uploads_info.append({
                    "uploadId": upload_id,
                    "name": finfo["name"],
                    "size": file_size,
                })
                self.file_store.update_meta(upload_id, **{
                    "file_path": str(final_path),
                    "original_name": finfo["name"],
                    "size": file_size,
                })

                if self.server_ref and self.server_ref.on_file_received:
                    self.server_ref.on_file_received(upload_id, finfo["name"])

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
            else:
                file_data = session.received.get(fid)
                if file_data is None:
                    continue
                upload_id = self.file_store.create_upload(
                    finfo["name"], file_data
                )
                uploads_info.append({
                    "uploadId": upload_id,
                    "name": finfo["name"],
                    "size": len(file_data),
                })

                if self.server_ref and self.server_ref.on_file_received:
                    self.server_ref.on_file_received(upload_id, finfo["name"])

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

        self.chunk_store.cleanup_session(sid)

        self._sessions.remove(sid)
        self._send_json(200, {
            "status": "seeding" if auto_seed else "idle",
            "uploads": uploads_info,
        })

    def _handle_upload_status(self, sid: str) -> None:
        """GET /api/upload/<sid> — poll session status, optionally with chunk details."""
        if not self._check_auth_and_rate():
            return
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)

        session = self._sessions.get(sid)
        if not session:
            self._send_json(200, {"sessionId": sid, "status": "expired"})
            return

        file_id = (qs.get("fileId") or [None])[0]
        token = (qs.get("token") or [None])[0]

        base_response: dict[str, Any] = {
            "sessionId": sid,
            "status": "active",
            "files_received": len(session.received) + len(session.chunked_files),
            "files_total": len(session.file_ids),
            "seed_status": session.seed_status,
        }

        if file_id:
            if token != session.file_tokens.get(file_id):
                self._send_error(403, "Invalid file token")
                return
            chunk_status = self.chunk_store.get_chunk_status(sid, file_id)
            base_response["file_chunks"] = {file_id: chunk_status} if chunk_status else {}
            self._send_json(200, base_response)
            return

        received_list = []
        for fid in session.file_ids:
            if fid in session.chunked_files:
                chunk_status = self.chunk_store.get_chunk_status(sid, fid)
                if chunk_status:
                    received_list.append({
                        "fileId": fid,
                        "name": session.files[fid]["name"],
                        "size": session.files[fid]["size"],
                        "chunked": True,
                        "chunksReceived": len(chunk_status["chunksReceived"]),
                        "totalChunks": chunk_status["totalChunks"],
                    })
            elif fid in session.received:
                received_list.append({
                    "fileId": fid,
                    "name": session.files[fid]["name"],
                    "size": len(session.received[fid]),
                    "chunked": False,
                })
        self._send_json(200, {**base_response, "received": received_list})

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

    def _handle_disconnect(self) -> None:
        """POST /api/disconnect — client requests graceful disconnect."""
        # No rate limit or auth check — always allow graceful disconnect
        ip = self._client_ip
        self._devices.unregister(ip)
        LOGGER.info("Device %s disconnected gracefully", ip)
        self._send_json(200, {"status": "disconnected"})

    def _handle_list_devices(self) -> None:
        """GET /api/devices — list currently connected devices."""
        self._send_json(200, {"devices": self._devices.list_devices(),
                              "count": len(self._devices._devices)})

    def _handle_list_files(self) -> None:
        """GET /api/files — list files shared by the PC user."""
        if not self._check_auth_and_rate():
            return

        shared = getattr(self.server_ref, 'shared_files', [])
        entries: list[dict] = []
        for fp in shared:
            if not fp.exists() or not fp.is_file():
                continue
            try:
                st = fp.stat()
            except OSError:
                continue
            entries.append({
                "path": str(fp),
                "name": fp.name,
                "type": "file",
                "size": st.st_size,
                "mtime": st.st_mtime,
            })
        entries.sort(key=lambda e: e["name"].lower())
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
        shared = getattr(self.server_ref, 'shared_files', [])
        if file_path not in shared:
            self._send_error(403, "File not shared by PC")
            return
        if not file_path.exists() or not file_path.is_file():
            self._send_error(404, "File not found")
            return

        try:
            file_size = file_path.stat().st_size
        except OSError:
            self._send_error(500, "Cannot access file")
            return

        # Support Range header for resume
        range_header = self.headers.get("Range", "")
        start = 0
        if range_header.startswith("bytes="):
            try:
                start = int(range_header.split("=")[1].split("-")[0])
                if start >= file_size:
                    self._send_error(416, "Range not satisfiable")
                    return
            except (ValueError, IndexError):
                start = 0

        if start > 0:
            self.send_response(206)
            self.send_header("Content-Range",
                             f"bytes {start}-{file_size - 1}/{file_size}")
            content_length = file_size - start
        else:
            self.send_response(200)
            content_length = file_size

        safe_name = file_path.name.encode("ascii", "replace").decode("ascii")
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition",
                         f'attachment; filename="{safe_name}"')
        self.send_header("Content-Length", str(content_length))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        sent = 0
        with open(file_path, "rb") as f:
            if start > 0:
                f.seek(start)
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                    sent += len(chunk)
                    if self.on_download_progress:
                        self.on_download_progress(file_path.name, sent, file_size, self._client_ip)
                except (ConnectionError, BrokenPipeError):
                    break
        if self.on_file_downloaded:
            try:
                self.on_file_downloaded(file_path.name, file_size, self._client_ip)
            except Exception:
                LOGGER.exception("Error in on_file_downloaded callback")

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
        self.chunk_store = ChunkStore(config.upload_receive_dir)
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.on_seed_ready: Callable | None = None
        self.on_file_received: Callable | None = None
        self.on_device_connected: Callable | None = None
        self.on_upload_progress: Callable | None = None
        self.on_file_downloaded: Callable | None = None
        self.on_download_progress: Callable | None = None
        self.serve_dirs: list[Path] | None = None
        self.shared_files: list[Path] = []
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

        self._full_token = secrets.token_hex(32)  # 64 hex chars
        self.serve_dirs = serve_dirs

        LanRequestHandler.config = self.config
        LanRequestHandler.file_store = self.file_store
        LanRequestHandler.chunk_store = self.chunk_store
        LanRequestHandler.qr_token = self.qr_token
        LanRequestHandler.full_token = self._full_token
        LanRequestHandler.on_seed_ready = self.on_seed_ready
        LanRequestHandler.on_file_downloaded = self.on_file_downloaded
        LanRequestHandler.on_download_progress = self.on_download_progress
        LanRequestHandler.server_ref = self
        LanRequestHandler._serve_dirs = self.serve_dirs

        self._server = HTTPServer(("0.0.0.0", port), LanRequestHandler)
        actual_port = self._server.server_port
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        LOGGER.info("LAN server started on 0.0.0.0:%d", actual_port)
        LOGGER.info("QR token: %s", self.qr_token)
        return actual_port

    def add_shared_files(self, paths: list[Path]) -> None:
        """Add files to the shared file list (deduplicated)."""
        existing = set(self.shared_files)
        for p in paths:
            if p not in existing and p.is_file():
                self.shared_files.append(p)
                existing.add(p)

    def remove_shared_file(self, path: Path) -> None:
        """Remove a file from the shared list."""
        self.shared_files = [f for f in self.shared_files if f != path]

    def clear_shared_files(self) -> None:
        self.shared_files.clear()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server = None
            self._thread = None
            self._full_token = ""
            self.shared_files.clear()
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
