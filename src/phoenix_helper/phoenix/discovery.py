from __future__ import annotations

from pathlib import Path

from phoenix_helper.torrent.inspector import inspect_torrent


def discover_tracker_from_torrent(path: Path) -> str:
    return inspect_torrent(path).announce


def discover_tracker_from_default_sample() -> str:
    sample = Path("测试下载.torrent")
    if not sample.exists():
        return ""
    return discover_tracker_from_torrent(sample)
