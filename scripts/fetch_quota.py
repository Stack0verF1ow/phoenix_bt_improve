"""Fetch daily upload quota from phoenix upload page.

Usage: python fetch_quota.py <upload_url> <profile_dir>

Prints the remaining upload count to stdout.
Uses cached cookies (requests) for speed; falls back to Selenium on first run.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests


COOKIES_FILE = "cookies.json"


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: fetch_quota.py <upload_url> <profile_dir>", file=sys.stderr)
        return 1

    upload_url = sys.argv[1]
    profile_dir = Path(sys.argv[2])
    cookies_path = profile_dir / COOKIES_FILE

    # Try fast path: requests with cached cookies
    if cookies_path.exists():
        print("使用缓存 cookies 获取...", file=sys.stderr)
        count = _fetch_with_requests(upload_url, cookies_path)
        if count is not None:
            print(f"快速获取成功: {count}", file=sys.stderr)
            print(count)
            return 0
        print("缓存 cookies 失效，回退到 Selenium", file=sys.stderr)

    # Fallback: Selenium (slow, but also refreshes cookies)
    print("使用 Selenium 获取...", file=sys.stderr)
    count = _fetch_with_selenium(upload_url, profile_dir, cookies_path)
    if count is not None:
        print(count)
        return 0

    print("ERROR: 无法获取上传次数", file=sys.stderr)
    return 1


def _fetch_with_requests(upload_url: str, cookies_path: Path) -> str | None:
    """Try to fetch quota using requests + cached cookies. Returns count or None."""
    try:
        data = json.loads(cookies_path.read_text(encoding="utf-8"))
        session = requests.Session()
        for c in data:
            session.cookies.set(c["name"], c["value"], domain=c.get("domain", ""))

        resp = session.get(upload_url, timeout=10)
        if "login" in resp.url.lower():
            return None

        text = resp.text
        # Parse: <span id="cpContent__cphContent_lblCountUpload">4</span>
        marker = "cpContent__cphContent_lblCountUpload"
        idx = text.find(marker)
        if idx < 0:
            return None
        start = text.find(">", idx) + 1
        end = text.find("<", start)
        if start > 0 and end > start:
            return text[start:end].strip()
        return None
    except Exception:
        return None


def _fetch_with_selenium(upload_url: str, profile_dir: Path, cookies_path: Path) -> str | None:
    """Fetch quota via Selenium and cache cookies for next time."""
    from selenium import webdriver
    from selenium.webdriver.edge.options import Options as EdgeOptions

    options = EdgeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1280,900")
    options.add_argument("--no-sandbox")
    options.add_argument(f"--user-data-dir={profile_dir}")
    options.add_argument("--profile-directory=Default")

    driver = webdriver.Edge(options=options)
    try:
        driver.get(upload_url)
        time.sleep(2)

        # Cache cookies for future fast requests
        try:
            cookies = driver.get_cookies()
            cookies_path.write_text(json.dumps(cookies, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

        count = driver.execute_script(
            "var e=document.getElementById('cpContent__cphContent_lblCountUpload');"
            "return e?e.textContent.trim():'';"
        )
        return count if count else None
    except Exception as e:
        print(f"Selenium error: {e}", file=sys.stderr)
        return None
    finally:
        driver.quit()


if __name__ == "__main__":
    raise SystemExit(main())
