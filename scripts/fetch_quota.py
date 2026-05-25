"""Fetch daily upload quota from phoenix upload page.

Usage: python fetch_quota.py <upload_url> <profile_dir> [--browser edge|chrome|firefox]

Prints the remaining upload count to stdout.
Uses cached cookies (requests) for speed; falls back to Selenium on first run.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

from driver_factory import create_driver


COOKIES_FILE = "cookies.json"


def main() -> int:
    args = _parse_args()
    upload_url = args["upload_url"]
    profile_dir = Path(args["profile_dir"])
    browser = args["browser"]
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

    # Fallback: Selenium
    print("使用 Selenium 获取...", file=sys.stderr)
    count = _fetch_with_selenium(upload_url, str(profile_dir), cookies_path, browser)
    if count is not None:
        print(count)
        return 0

    print("ERROR: 无法获取上传次数", file=sys.stderr)
    return 1


def _parse_args() -> dict:
    positional = []
    kwargs = {"browser": "edge"}

    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "--browser" and i + 1 < len(sys.argv):
            kwargs["browser"] = sys.argv[i + 1]
            i += 2
        else:
            positional.append(arg)
            i += 1

    if len(positional) < 2:
        print("Usage: fetch_quota.py <upload_url> <profile_dir> [--browser edge|chrome|firefox]", file=sys.stderr)
        sys.exit(1)

    kwargs["upload_url"] = positional[0]
    kwargs["profile_dir"] = positional[1]
    return kwargs


def _fetch_with_requests(upload_url: str, cookies_path: Path) -> str | None:
    try:
        data = json.loads(cookies_path.read_text(encoding="utf-8"))
        session = requests.Session()
        for c in data:
            session.cookies.set(c["name"], c["value"], domain=c.get("domain", ""))

        resp = session.get(upload_url, timeout=10)
        if "login" in resp.url.lower():
            return None

        text = resp.text
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


def _fetch_with_selenium(upload_url: str, profile_dir: str, cookies_path: Path, browser: str) -> str | None:
    driver = create_driver(browser, profile_dir, headless=True)
    try:
        driver.get(upload_url)
        time.sleep(2)

        # Cache cookies
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
