"""Test HTTP-based torrent upload (bypassing WebEngine).

Usage: .build-venv/Scripts/python scripts/test_http_upload.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure src/ is on the path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from phoenix_helper.config import load_app_config, user_config_path
from phoenix_helper.models import ResourceDraft
from phoenix_helper.phoenix.client import PhoenixClient
from phoenix_helper.torrent.creator import create_torrent, recommended_piece_length

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
LOGGER = logging.getLogger("test_http_upload")


def main() -> int:
    config_path = user_config_path()
    if not config_path.exists():
        LOGGER.error("Config not found at %s", config_path)
        return 1

    config = load_app_config(config_path)
    if not config.cookie_header:
        LOGGER.error("No cookie configured. Please login first via the GUI.")
        return 1

    LOGGER.info("Site: %s", config.site_base_url)
    LOGGER.info("Upload URL: %s", config.upload_url)
    LOGGER.info("Cookie: %s...", config.cookie_header[:40])

    # Create a small test file
    test_dir = config.temp_dir / "http_upload_test"
    test_dir.mkdir(parents=True, exist_ok=True)
    test_file = test_dir / "hello.txt"
    test_file.write_text("Hello Phoenix BT! This is a test upload from phoenix-helper.")

    LOGGER.info("Creating test torrent...")
    torrent_path = test_dir / "hello.torrent"
    create_torrent(
        test_file,
        config.tracker_url,
        torrent_path,
        piece_length=recommended_piece_length(test_file.stat().st_size),
    )
    LOGGER.info("Test torrent created: %s (%d bytes)", torrent_path, torrent_path.stat().st_size)

    # Build a ResourceDraft
    draft = ResourceDraft(
        source_path=test_file,
        title="[测试] HTTP上传测试 - 请忽略",
        subtitle="测试HTTP直连上传",
        description="这是一个自动测试，用于验证HTTP直连上传是否可行。如果看到请忽略。",
        category="0",
        tags=["测试"],
        files=[],
        confirmed_compliance=True,
    )

    # Try HTTP upload
    LOGGER.info("=" * 60)
    LOGGER.info("Attempting HTTP upload...")
    LOGGER.info("=" * 60)

    client = PhoenixClient(config)
    result = client.upload_torrent(draft, torrent_path)

    LOGGER.info("=" * 60)
    LOGGER.info("Result: success=%s", result.success)
    LOGGER.info("Message: %s", result.message)
    LOGGER.info("Detail URL: %s", result.detail_url)
    LOGGER.info("Torrent URL: %s", result.torrent_url)

    if result.success:
        LOGGER.info("HTTP upload SUCCEEDED!")
        return 0
    else:
        LOGGER.error("HTTP upload FAILED.")
        LOGGER.info("Check debug HTML saved in: %s", config.temp_dir)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
