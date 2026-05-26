from __future__ import annotations

import os
import string
from pathlib import Path


def find_utorrent_executable() -> Path | None:
    candidates = _candidate_paths()
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return _search_common()


def _get_all_drives() -> list[Path]:
    """Get all available drive roots on Windows (C:, D:, etc.)."""
    drives = []
    for letter in string.ascii_uppercase:
        drive = f"{letter}:\\"
        if os.path.exists(drive):
            drives.append(Path(drive))
    return drives


def _candidate_paths() -> list[Path]:
    """Build a list of likely uTorrent exe locations."""
    candidates: list[Path] = []

    # Search ProgramFiles and APPDATA on all drives
    for drive in _get_all_drives():
        for prog_dir in ("Program Files", "Program Files (x86)", "ProgramFiles"):
            candidates.extend([
                drive / prog_dir / "uTorrent" / "uTorrent.exe",
                drive / prog_dir / "µTorrent" / "uTorrent.exe",
                drive / prog_dir / "BitTorrent" / "BitTorrent.exe",
            ])
        # Also check drive roots for portable installs
        candidates.extend([
            drive / "uTorrent" / "uTorrent.exe",
            drive / "µTorrent" / "uTorrent.exe",
            drive / "BitTorrent" / "BitTorrent.exe",
        ])

    # Also check env-var-derived paths (original behavior)
    env_names = ["ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA", "APPDATA"]
    for name in env_names:
        value = os.environ.get(name)
        if value:
            root = Path(value)
            candidates.extend([
                root / "uTorrent" / "uTorrent.exe",
                root / "µTorrent" / "uTorrent.exe",
                root / "BitTorrent" / "BitTorrent.exe",
            ])

    return candidates


def _search_common() -> Path | None:
    """Search common uTorrent install locations by checking dirs, not full rglob."""
    exe_names = {"utorrent.exe", "µtorrent.exe", "bittorrent.exe"}

    for drive in _get_all_drives():
        for prog_dir in ("Program Files", "Program Files (x86)", "ProgramFiles"):
            prog_path = drive / prog_dir
            if not prog_path.exists():
                continue
            for entry in prog_path.iterdir():
                if entry.is_dir() and entry.name.lower() in ("utorrent", "µtorrent", "bittorrent"):
                    for exe in entry.iterdir():
                        if exe.is_file() and exe.name.lower() in exe_names:
                            return exe

    return None
