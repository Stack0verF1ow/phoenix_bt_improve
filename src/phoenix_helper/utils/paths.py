from __future__ import annotations

from pathlib import Path


def safe_filename(name: str, replacement: str = "_") -> str:
    invalid = '<>:"/\\|?*\0'
    cleaned = "".join(replacement if char in invalid else char for char in name).strip()
    return cleaned or "untitled"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    index = 1
    while True:
        candidate = parent / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1
