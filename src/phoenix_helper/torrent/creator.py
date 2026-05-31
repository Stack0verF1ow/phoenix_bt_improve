from __future__ import annotations

import hashlib
import math
from pathlib import Path
from time import time
from typing import Callable

from phoenix_helper.models import FileEntry, scan_files
from phoenix_helper.torrent.bencode import BValue, encode

ProgressCallback = Callable[[int, int], None]

DEFAULT_PIECE_LENGTH = 1024 * 1024


def create_torrent(
    source_path: Path,
    announce: str,
    output_path: Path,
    *,
    piece_length: int = DEFAULT_PIECE_LENGTH,
    created_by: str = "phoenix-helper/0.1.0",
    private: bool = True,
    progress: ProgressCallback | None = None,
) -> Path:
    source_path = source_path.expanduser().resolve()
    output_path = output_path.expanduser().resolve()
    if not source_path.exists():
        raise FileNotFoundError(source_path)
    if piece_length <= 0:
        raise ValueError("piece_length must be positive")

    files = scan_files(source_path)
    if not files:
        raise ValueError("source path contains no files")

    info: dict[bytes, BValue] = {
        b"name": source_path.name.encode("utf-8"),
        b"piece length": piece_length,
        b"pieces": _hash_pieces(files, piece_length, progress),
    }
    if private:
        info[b"private"] = 1

    if source_path.is_file():
        info[b"length"] = source_path.stat().st_size
    else:
        info[b"files"] = [
            {
                b"length": entry.size,
                b"path": [part.encode("utf-8") for part in entry.relative_path.parts],
            }
            for entry in files
        ]

    metainfo: dict[bytes, BValue] = {
        b"creation date": int(time()),
        b"created by": created_by.encode("utf-8"),
        b"encoding": b"UTF-8",
        b"info": info,
    }
    if announce:
        metainfo[b"announce"] = announce.encode("utf-8")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(encode(metainfo))
    return output_path


def _hash_pieces(files: list[FileEntry], piece_length: int, progress: ProgressCallback | None) -> bytes:
    total_size = sum(entry.size for entry in files)
    processed = 0
    pieces: list[bytes] = []
    buffer = bytearray()

    for entry in files:
        with entry.path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                processed += len(chunk)
                buffer.extend(chunk)
                while len(buffer) >= piece_length:
                    piece = bytes(buffer[:piece_length])
                    del buffer[:piece_length]
                    pieces.append(hashlib.sha1(piece).digest())
                if progress is not None:
                    progress(processed, total_size)

    if buffer or total_size == 0:
        pieces.append(hashlib.sha1(bytes(buffer)).digest())
    if progress is not None:
        progress(total_size, total_size)
    return b"".join(pieces)


def recommended_piece_length(total_size: int) -> int:
    if total_size <= 0:
        return 16 * 1024
    target_pieces = 1500
    raw = max(16 * 1024, math.ceil(total_size / target_pieces))
    piece = 16 * 1024
    while piece < raw:
        piece *= 2
    return min(piece, 16 * 1024 * 1024)
