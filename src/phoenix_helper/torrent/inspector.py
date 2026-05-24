from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from phoenix_helper.torrent.bencode import BValue, as_text, decode, encode, require_bytes, require_dict, require_int


@dataclass(frozen=True, slots=True)
class TorrentFileInfo:
    path: str
    size: int


@dataclass(frozen=True, slots=True)
class TorrentInfo:
    name: str
    announce: str
    private: bool
    piece_length: int
    info_hash: str
    total_size: int
    files: list[TorrentFileInfo]


def inspect_torrent(path: Path) -> TorrentInfo:
    data = path.expanduser().resolve().read_bytes()
    metainfo = require_dict(decode(data), "metainfo")
    info = require_dict(metainfo.get(b"info"), "info")
    announce = as_text(metainfo.get(b"announce", b""))
    name = as_text(require_bytes(info.get(b"name"), "info.name"))
    private = bool(info.get(b"private", 0))
    piece_length = require_int(info.get(b"piece length"), "info.piece length")
    info_hash = hashlib.sha1(encode(info)).hexdigest()
    files = _extract_files(info, name)
    total_size = sum(file.size for file in files)
    return TorrentInfo(
        name=name,
        announce=announce,
        private=private,
        piece_length=piece_length,
        info_hash=info_hash,
        total_size=total_size,
        files=files,
    )


def _extract_files(info: dict[bytes, BValue], name: str) -> list[TorrentFileInfo]:
    if b"files" not in info:
        return [TorrentFileInfo(name, require_int(info.get(b"length"), "info.length"))]

    files_value = info[b"files"]
    if not isinstance(files_value, list):
        raise ValueError("info.files must be a list")

    files: list[TorrentFileInfo] = []
    for index, item in enumerate(files_value):
        file_info = require_dict(item, f"info.files[{index}]")
        length = require_int(file_info.get(b"length"), f"info.files[{index}].length")
        path_value = file_info.get(b"path")
        if not isinstance(path_value, list):
            raise ValueError(f"info.files[{index}].path must be a list")
        parts = [as_text(require_bytes(part, f"info.files[{index}].path[]")) for part in path_value]
        files.append(TorrentFileInfo("/".join([name, *parts]), length))
    return files


def compare_torrents(left: Path, right: Path) -> dict[str, tuple[object, object]]:
    left_info = inspect_torrent(left)
    right_info = inspect_torrent(right)
    diff: dict[str, tuple[object, object]] = {}
    for field in ("name", "announce", "private", "piece_length", "info_hash", "total_size"):
        left_value = getattr(left_info, field)
        right_value = getattr(right_info, field)
        if left_value != right_value:
            diff[field] = (left_value, right_value)
    if left_info.files != right_info.files:
        diff["files"] = (left_info.files, right_info.files)
    return diff
