"""Full end-to-end test: HTTP upload + download final torrent."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from phoenix_helper.config import load_app_config, user_config_path
from phoenix_helper.models import ResourceDraft
from phoenix_helper.phoenix.client import PhoenixClient
from phoenix_helper.torrent.creator import create_torrent, recommended_piece_length
from phoenix_helper.utils.paths import safe_filename, unique_path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
LOGGER = logging.getLogger("test_e2e")


def main() -> int:
    config = load_app_config(user_config_path())
    if not config.cookie_header:
        LOGGER.error("No cookie configured.")
        return 1

    # Create test file + torrent
    test_dir = config.temp_dir / "http_e2e_test"
    test_dir.mkdir(parents=True, exist_ok=True)
    test_file = test_dir / "e2e_test.txt"
    test_file.write_text("E2E HTTP upload test - " + str(Path(__file__).stat().st_mtime))

    torrent_path = test_dir / "e2e_test.torrent"
    create_torrent(
        test_file, config.tracker_url, torrent_path,
        piece_length=recommended_piece_length(test_file.stat().st_size),
    )
    LOGGER.info("Torrent: %s (%d bytes)", torrent_path, torrent_path.stat().st_size)

    # Upload via HTTP
    draft = ResourceDraft(
        source_path=test_file,
        title="[测试] HTTP E2E上传测试",
        subtitle="测试完整上传下载流程",
        description="E2E测试，验证HTTP上传+下载种子。",
        category="0",
        tags=["测试"],
        files=[],
        confirmed_compliance=True,
    )

    client = PhoenixClient(config)
    result = client.upload_torrent(draft, torrent_path)

    LOGGER.info("Upload result: success=%s", result.success)
    LOGGER.info("Detail URL: %s", result.detail_url)
    LOGGER.info("Torrent URL: %s", result.torrent_url)

    if not result.success:
        LOGGER.error("Upload failed: %s", result.message)
        return 1

    # Download final torrent
    if result.torrent_url:
        LOGGER.info("Downloading final torrent...")
        final_path = client.download_final_torrent(
            result.torrent_url, draft.title, config.final_torrent_dir
        )
        LOGGER.info("Final torrent saved: %s (%d bytes)", final_path, final_path.stat().st_size)
        LOGGER.info("\n=== SUCCESS! Full HTTP upload+download works! ===")
        return 0
    else:
        LOGGER.warning("Upload succeeded but no torrent URL. Manual download needed.")
        LOGGER.info("Detail page: %s", result.detail_url)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
