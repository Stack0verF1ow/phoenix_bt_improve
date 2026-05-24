from __future__ import annotations

import argparse
from pathlib import Path

from phoenix_helper.torrent.inspector import compare_torrents, inspect_torrent
from phoenix_helper.models import format_size


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect or compare torrent files.")
    parser.add_argument("torrent", type=Path)
    parser.add_argument("other", type=Path, nargs="?")
    args = parser.parse_args()

    if args.other:
        diff = compare_torrents(args.torrent, args.other)
        if not diff:
            print("No differences in inspected fields.")
            return 0
        for field, (left, right) in diff.items():
            print(f"{field}: {left!r} -> {right!r}")
        return 0

    info = inspect_torrent(args.torrent)
    print(f"Name: {info.name}")
    print(f"Announce: {info.announce}")
    print(f"Private: {info.private}")
    print(f"Piece length: {format_size(info.piece_length)}")
    print(f"Info hash: {info.info_hash}")
    print(f"Total size: {format_size(info.total_size)}")
    print("Files:")
    for file in info.files:
        print(f"- {file.path} ({format_size(file.size)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
