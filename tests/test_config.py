from pathlib import Path

from phoenix_helper.config import AppConfig, load_app_config, save_app_config


def test_save_and_load_app_config_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    config = AppConfig(
        tracker_url="http://tracker.example/announce",
        cookie_header="session=secret",
        utorrent_executable=r"C:\Program Files\uTorrent\uTorrent.exe",
        utorrent_webui_password="webui-secret",
        final_torrent_dir=Path("custom/final"),
    )

    save_app_config(config, path)
    loaded = load_app_config(path)

    assert loaded.tracker_url == "http://tracker.example/announce"
    assert loaded.cookie_header == "session=secret"
    assert loaded.utorrent_executable == r"C:\Program Files\uTorrent\uTorrent.exe"
    assert loaded.utorrent_webui_password == "webui-secret"
    assert loaded.final_torrent_dir == Path("custom/final")


def test_save_app_config_does_not_store_secrets_as_plain_text(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    config = AppConfig(cookie_header="session=secret", utorrent_webui_password="webui-secret")

    save_app_config(config, path)
    text = path.read_text(encoding="utf-8")

    assert "session=secret" not in text
    assert "webui-secret" not in text
