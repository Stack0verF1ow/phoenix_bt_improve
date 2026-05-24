from __future__ import annotations

import os
from pathlib import Path


def find_utorrent_executable() -> Path | None:
    candidates = _candidate_paths()
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return _search_limited()


def _candidate_paths() -> list[Path]:
    env_names = ["ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA", "APPDATA"]
    roots = [Path(value) for name in env_names if (value := os.environ.get(name))]
    candidates: list[Path] = []
    for root in roots:
        candidates.extend(
            [
                root / "uTorrent" / "uTorrent.exe",
                root / "µTorrent" / "uTorrent.exe",
                root / "BitTorrent" / "BitTorrent.exe",
            ]
        )
    return candidates


def _search_limited() -> Path | None:
    roots = [
        os.environ.get("LOCALAPPDATA"),
        os.environ.get("APPDATA"),
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
    ]
    names = {"utorrent.exe", "µtorrent.exe"}
    for root_value in roots:
        if not root_value:
            continue
        root = Path(root_value)
        if not root.exists():
            continue
        for path in root.rglob("*.exe"):
            if path.name.lower() in names:
                return path
    return None
