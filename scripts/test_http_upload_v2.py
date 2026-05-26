"""Test HTTP upload with proper cookie jar handling.

The key difference: instead of setting Cookie as a session-level header
(which overrides the cookie jar), set cookies individually so that
Set-Cookie responses (like ASP.NET_SessionId) are properly handled.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from phoenix_helper.config import load_app_config, user_config_path
from phoenix_helper.models import ResourceDraft
from phoenix_helper.phoenix.client import PhoenixClient
from phoenix_helper.phoenix.forms import parse_upload_form
from phoenix_helper.phoenix.parser import (
    extract_error_message,
    find_detail_url,
    find_torrent_url,
)
from phoenix_helper.torrent.creator import create_torrent, recommended_piece_length
from urllib.parse import urljoin
import requests

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
LOGGER = logging.getLogger("test_http_v2")


def _set_cookies_from_header(session: requests.Session, cookie_header: str, domain: str) -> None:
    """Parse cookie header and set each cookie in the session's cookie jar."""
    for pair in cookie_header.split(";"):
        pair = pair.strip()
        if "=" not in pair:
            continue
        name, value = pair.split("=", 1)
        session.cookies.set(name.strip(), value.strip(), domain=domain, path="/")
    LOGGER.info("Set %d cookies into jar from header", cookie_header.count("="))


def main() -> int:
    config_path = user_config_path()
    config = load_app_config(config_path)

    if not config.cookie_header:
        LOGGER.error("No cookie configured.")
        return 1

    LOGGER.info("Cookie header (%d chars): %s...", len(config.cookie_header), config.cookie_header[:80])

    # Create test torrent
    test_dir = config.temp_dir / "http_upload_test2"
    test_dir.mkdir(parents=True, exist_ok=True)
    test_file = test_dir / "test.txt"
    test_file.write_text("HTTP upload test - phoenix-helper " + str(Path(__file__).stat().st_mtime))

    torrent_path = test_dir / "test.torrent"
    create_torrent(
        test_file,
        config.tracker_url,
        torrent_path,
        piece_length=recommended_piece_length(test_file.stat().st_size),
    )
    LOGGER.info("Test torrent: %s (%d bytes)", torrent_path, torrent_path.stat().st_size)

    # ----- Approach: cookies in jar, not session-level header -----
    LOGGER.info("=" * 60)
    LOGGER.info("Attempt 1: Cookies in jar (not session-level header)")
    LOGGER.info("=" * 60)

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })
    _set_cookies_from_header(session, config.cookie_header, "phoenix.stu.edu.cn")

    # Step 1: GET upload page
    LOGGER.info("GET upload form...")
    resp = session.get(config.upload_url, timeout=20)
    LOGGER.info("GET status=%d, url=%s", resp.status_code, resp.url)
    LOGGER.info("Cookies after GET: %s", list(session.cookies))

    if resp.status_code != 200:
        LOGGER.error("Failed to get upload form")
        return 1

    upload_form = parse_upload_form(resp.text, config.site_base_url)
    LOGGER.info("Found form fields: %s", list(upload_form.fields.keys()))
    LOGGER.info("File field: %s", upload_form.file_field)

    # Step 2: POST upload
    post_url = urljoin(config.upload_url, upload_form.action or config.upload_url)
    data = dict(upload_form.fields)
    data[upload_form.title_field] = "[测试] HTTP上传测试2"
    data[upload_form.subtitle_field] = "测试Cookie Jar方式"
    data[upload_form.description_field] = "测试通过requests.Session cookie jar上传"
    data[upload_form.category_field] = "0"
    if upload_form.tags_field is not None:
        data[upload_form.tags_field] = "测试"
    if upload_form.tags_fid_field is not None:
        data[upload_form.tags_fid_field] = "0"
    if upload_form.submit_field is not None:
        data[upload_form.submit_field] = "上传"

    torrent_bytes = torrent_path.read_bytes()
    files = {
        upload_form.file_field: (torrent_path.name, torrent_bytes, "application/x-bittorrent"),
    }

    headers = {
        "Referer": config.upload_url,
        "Origin": config.site_base_url,
    }

    LOGGER.info("POST upload (cookies in jar)...")
    LOGGER.info("Session cookies before POST: %s", list(session.cookies))
    resp2 = session.post(post_url, data=data, files=files, headers=headers, timeout=60)
    LOGGER.info("POST status=%d, url=%s", resp2.status_code, resp2.url)
    LOGGER.info("Cookies after POST: %s", list(session.cookies))

    # Save debug HTML
    debug_path = config.temp_dir / "upload_response_v2.html"
    debug_path.write_text(resp2.text, encoding="utf-8")
    LOGGER.info("Response saved: %s", debug_path)

    # Check result
    if "error.aspx" in resp2.url.lower():
        LOGGER.error("Server returned error page")
        LOGGER.info("Response text (first 500 chars): %s", resp2.text[:500])
        return 1

    if "detail.aspx" in resp2.url.lower() or "detail" in resp2.url.lower():
        LOGGER.info("SUCCESS! Redirected to detail page: %s", resp2.url)
        torrent_url = find_torrent_url(resp2.text, resp2.url)
        LOGGER.info("Torrent URL: %s", torrent_url)
        return 0

    detail_url = find_detail_url(resp2.text, config.site_base_url)
    error = extract_error_message(resp2.text)

    if detail_url:
        LOGGER.info("Found detail URL in response: %s", detail_url)
        torrent_url = find_torrent_url(resp2.text, detail_url)
        LOGGER.info("Torrent URL: %s", torrent_url)
        return 0

    if error:
        LOGGER.error("Error from server: %s", error)
    else:
        LOGGER.warning("No detail URL or error found. Same page? %s", resp2.url)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
