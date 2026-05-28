from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


class FileStore:
    """Manage files received from mobile uploads on disk."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create_upload(self, original_name: str, file_data: bytes) -> str:
        """Save an uploaded file directly in base_dir and return its upload ID."""
        upload_id = str(uuid.uuid4())
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # Avoid overwriting: append suffix if file exists
        file_path = self.base_dir / original_name
        if file_path.exists():
            stem = file_path.stem
            suffix = file_path.suffix
            counter = 1
            while file_path.exists():
                file_path = self.base_dir / f"{stem}_{counter}{suffix}"
                counter += 1

        file_path.write_bytes(file_data)

        meta = {
            "id": upload_id,
            "original_name": original_name,
            "size": len(file_data),
            "file_path": str(file_path),
            "uploaded_at": datetime.now().isoformat(),
            "auto_seed": False,
            "seed_status": "idle",
            "seed_detail_url": "",
            "seed_torrent_url": "",
            "title": "",
            "category": "0",
        }
        self._write_meta(upload_id, meta)
        return upload_id

    def update_meta(self, upload_id: str, **kwargs: Any) -> None:
        meta_path = self._meta_path(upload_id)
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta.update(kwargs)
            self._write_meta(upload_id, meta)

    def get_meta(self, upload_id: str) -> dict[str, Any] | None:
        meta_path = self._meta_path(upload_id)
        if not meta_path.exists():
            return None
        return json.loads(meta_path.read_text(encoding="utf-8"))

    def get_file_path(self, upload_id: str) -> Path | None:
        meta = self.get_meta(upload_id)
        if meta:
            path = Path(meta["file_path"])
            if path.exists():
                return path
        return None

    def list_all(self) -> list[dict[str, Any]]:
        entries = []
        meta_dir = self.base_dir / ".meta"
        if not meta_dir.exists():
            return entries
        for meta_file in sorted(meta_dir.iterdir()):
            if meta_file.suffix == ".json":
                try:
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                    entries.append(meta)
                except Exception:
                    continue
        return entries

    def remove(self, upload_id: str) -> None:
        meta = self.get_meta(upload_id)
        if meta:
            file_path = Path(meta.get("file_path", ""))
            if file_path.exists() and file_path.is_file():
                file_path.unlink()
        meta_path = self._meta_path(upload_id)
        if meta_path.exists():
            meta_path.unlink()

    def _meta_path(self, upload_id: str) -> Path:
        meta_dir = self.base_dir / ".meta"
        meta_dir.mkdir(parents=True, exist_ok=True)
        return meta_dir / f"{upload_id}.json"

    def _write_meta(self, upload_id: str, meta: dict) -> None:
        meta_path = self._meta_path(upload_id)
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
