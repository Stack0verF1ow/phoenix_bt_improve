"""Chunk-aware temporary file storage for resumable uploads.

Manages .part/{sessionId}/ directories containing:
  {fileId}.meta.json  — file metadata + chunk status
  {fileId}.data       — accumulated file (seek-write per chunk)
"""

from __future__ import annotations

import binascii
import json
import logging
import shutil
import threading
import time
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

_DEFAULT_CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB


class ChunkStore:
    """Manages chunked temporary files on disk."""

    def __init__(self, base_dir: Path, chunk_size: int = _DEFAULT_CHUNK_SIZE) -> None:
        self.base_dir = base_dir
        self.chunk_size = chunk_size
        self._lock = threading.Lock()

    def prepare_file(
        self,
        session_id: str,
        file_id: str,
        file_name: str,
        file_size: int,
        file_type: str,
        file_token: str,
        chunk_size: int | None = None,
    ) -> dict[str, Any]:
        cs = chunk_size or self.chunk_size
        total_chunks = (file_size + cs - 1) // cs if file_size > 0 else 1

        part_dir = self.base_dir / ".part" / session_id
        part_dir.mkdir(parents=True, exist_ok=True)

        meta: dict[str, Any] = {
            "fileName": file_name,
            "fileSize": file_size,
            "chunkSize": cs,
            "totalChunks": total_chunks,
            "chunksReceived": [],
            "chunkChecksums": {},
            "createdAt": int(time.time()),
            "fileToken": file_token,
            "fileType": file_type,
        }
        meta_path = part_dir / f"{file_id}.meta.json"
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        data_path = part_dir / f"{file_id}.data"
        if file_size > 0:
            with open(data_path, "wb") as f:
                f.seek(file_size - 1)
                f.write(b"\x00")
        else:
            data_path.touch()

        return meta

    def write_chunk(
        self,
        session_id: str,
        file_id: str,
        chunk_index: int,
        data: bytes,
        expected_crc32: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            meta = self._load_meta(session_id, file_id)
            if meta is None:
                raise FileNotFoundError(f"No meta for {session_id}/{file_id}")

            chunks_received: list[int] = meta["chunksReceived"]
            if chunk_index in chunks_received:
                return {
                    "status": "duplicate",
                    "fileId": file_id,
                    "chunkIndex": chunk_index,
                    "chunksReceived": chunks_received,
                    "totalChunks": meta["totalChunks"],
                }

            computed_crc = format(binascii.crc32(data) & 0xFFFFFFFF, "08x")
            if expected_crc32 and computed_crc != expected_crc32.lower():
                return {
                    "status": "checksum_mismatch",
                    "fileId": file_id,
                    "chunkIndex": chunk_index,
                    "computedCrc32": computed_crc,
                }

            offset = chunk_index * meta["chunkSize"]
            data_path = self.base_dir / ".part" / session_id / f"{file_id}.data"
            with open(data_path, "r+b") as f:
                f.seek(offset)
                f.write(data)

            chunks_received.append(chunk_index)
            checksums: dict[str, str] = meta.get("chunkChecksums", {})
            checksums[str(chunk_index)] = computed_crc
            meta["chunksReceived"] = chunks_received
            meta["chunkChecksums"] = checksums
            self._save_meta(session_id, file_id, meta)

            return {
                "status": "chunk_received",
                "fileId": file_id,
                "chunkIndex": chunk_index,
                "chunksReceived": chunks_received,
                "totalChunks": meta["totalChunks"],
            }

    def get_chunk_status(self, session_id: str, file_id: str) -> dict[str, Any] | None:
        meta = self._load_meta(session_id, file_id)
        if meta is None:
            return None
        return {
            "totalChunks": meta["totalChunks"],
            "chunksReceived": meta["chunksReceived"],
            "fileSize": meta["fileSize"],
            "chunkSize": meta["chunkSize"],
            "fileName": meta["fileName"],
        }

    def get_all_file_status(self, session_id: str) -> dict[str, dict[str, Any]]:
        part_dir = self.base_dir / ".part" / session_id
        if not part_dir.exists():
            return {}
        result: dict[str, dict[str, Any]] = {}
        for meta_path in part_dir.glob("*.meta.json"):
            file_id = meta_path.stem.replace(".meta", "")
            status = self.get_chunk_status(session_id, file_id)
            if status:
                result[file_id] = status
        return result

    def finalize_file(self, session_id: str, file_id: str, expected_sha256: str | None = None) -> Path | None:
        meta = self._load_meta(session_id, file_id)
        if meta is None:
            return None

        total = meta["totalChunks"]
        received = set(meta["chunksReceived"])
        if len(received) != total:
            missing = sorted(set(range(total)) - received)
            LOGGER.warning("File %s/%s incomplete: missing chunks %s", session_id, file_id, missing)
            return None

        data_path = self.base_dir / ".part" / session_id / f"{file_id}.data"

        if expected_sha256:
            import hashlib
            sha256 = hashlib.sha256()
            with open(data_path, "rb") as f:
                while True:
                    block = f.read(65536)
                    if not block:
                        break
                    sha256.update(block)
            if sha256.hexdigest() != expected_sha256.lower():
                LOGGER.error("SHA256 mismatch for %s/%s", session_id, file_id)
                return None

        final_name = meta["fileName"]
        final_path = self.base_dir / final_name
        if final_path.exists():
            stem = final_path.stem
            suffix = final_path.suffix
            counter = 1
            while final_path.exists():
                final_path = self.base_dir / f"{stem}_{counter}{suffix}"
                counter += 1

        data_path.rename(final_path)

        meta_path = self.base_dir / ".part" / session_id / f"{file_id}.meta.json"
        meta_path.unlink(missing_ok=True)

        part_dir = self.base_dir / ".part" / session_id
        remaining = list(part_dir.iterdir())
        if not remaining:
            try:
                part_dir.rmdir()
            except OSError:
                pass

        LOGGER.info("Finalized %s -> %s", file_id, final_path)
        return final_path

    def cleanup_session(self, session_id: str) -> None:
        part_dir = self.base_dir / ".part" / session_id
        if part_dir.exists():
            shutil.rmtree(part_dir, ignore_errors=True)
            LOGGER.info("Cleaned up session %s", session_id)

    def _load_meta(self, session_id: str, file_id: str) -> dict[str, Any] | None:
        meta_path = self.base_dir / ".part" / session_id / f"{file_id}.meta.json"
        if not meta_path.exists():
            return None
        return json.loads(meta_path.read_text(encoding="utf-8"))

    def _save_meta(self, session_id: str, file_id: str, meta: dict[str, Any]) -> None:
        meta_path = self.base_dir / ".part" / session_id / f"{file_id}.meta.json"
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")