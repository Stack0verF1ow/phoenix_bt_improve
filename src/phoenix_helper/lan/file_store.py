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
        """Save an uploaded file and return its upload ID."""
        upload_id = str(uuid.uuid4())
        upload_dir = self.base_dir / upload_id
        upload_dir.mkdir(parents=True, exist_ok=True)

        file_path = upload_dir / original_name
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
        for subdir in sorted(self.base_dir.iterdir()):
            if subdir.is_dir():
                meta = self.get_meta(subdir.name)
                if meta:
                    entries.append(meta)
        return entries

    def remove(self, upload_id: str) -> None:
        import shutil
        upload_dir = self.base_dir / upload_id
        if upload_dir.exists():
            shutil.rmtree(upload_dir)

    def _meta_path(self, upload_id: str) -> Path:
        return self.base_dir / upload_id / "meta.json"

    def _write_meta(self, upload_id: str, meta: dict) -> None:
        meta_path = self._meta_path(upload_id)
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
