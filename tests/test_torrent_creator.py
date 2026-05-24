from pathlib import Path

from phoenix_helper.torrent.creator import create_torrent
from phoenix_helper.torrent.inspector import inspect_torrent


def test_create_single_file_private_torrent(tmp_path: Path) -> None:
    source = tmp_path / "demo.txt"
    source.write_text("hello", encoding="utf-8")
    torrent_path = tmp_path / "demo.torrent"

    create_torrent(source, "http://tracker.example/announce", torrent_path, piece_length=16 * 1024)

    info = inspect_torrent(torrent_path)
    assert info.name == "demo.txt"
    assert info.announce == "http://tracker.example/announce"
    assert info.private is True
    assert info.total_size == 5
    assert info.files[0].path == "demo.txt"


def test_create_directory_torrent(tmp_path: Path) -> None:
    source_dir = tmp_path / "demo"
    source_dir.mkdir()
    (source_dir / "a.txt").write_text("a", encoding="utf-8")
    (source_dir / "b.txt").write_text("bb", encoding="utf-8")
    torrent_path = tmp_path / "demo.torrent"

    create_torrent(source_dir, "http://tracker.example/announce", torrent_path, piece_length=16 * 1024)

    info = inspect_torrent(torrent_path)
    assert info.name == "demo"
    assert info.total_size == 3
    assert [file.path for file in info.files] == ["demo/a.txt", "demo/b.txt"]
