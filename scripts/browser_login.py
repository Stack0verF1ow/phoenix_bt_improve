"""Open browser for user to log in to phoenix site. Saves cookies to persistent profile.

Usage: python browser_login.py <site_url> <profile_dir> [--browser edge|chrome|firefox]

Exits 0 on success, 1 on failure.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from driver_factory import create_driver


def main() -> int:
    args = _parse_args()
    site_url = args["site_url"]
    profile_dir = args["profile_dir"]
    browser = args["browser"]

    Path(profile_dir).mkdir(parents=True, exist_ok=True)

    print("正在启动浏览器...", file=sys.stderr)
    driver = create_driver(browser, profile_dir)

    try:
        parsed = urlparse(site_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        login_url = f"{base_url}/login.aspx"

        driver.get(login_url)
        time.sleep(2)

        print("请在浏览器窗口中登录金凤网站...", file=sys.stderr)
        print("登录成功后会自动检测并保存凭证。", file=sys.stderr)

        for i in range(100):
            time.sleep(3)
            if _is_logged_in(driver, base_url):
                print("登录成功！凭证已保存。", file=sys.stderr)
                print("SUCCESS")
                return 0
            if i % 10 == 9:
                print(f"等待登录... ({(i + 1) * 3}秒)", file=sys.stderr)

        print("ERROR: 登录超时（5分钟），请重试。", file=sys.stderr)
        return 1

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    finally:
        driver.quit()


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
        print("Usage: browser_login.py <site_url> <profile_dir> [--browser edge|chrome|firefox]", file=sys.stderr)
        sys.exit(1)

    kwargs["site_url"] = positional[0]
    kwargs["profile_dir"] = positional[1]
    return kwargs


def _is_logged_in(driver, base_url: str) -> bool:
    try:
        current_url = driver.current_url.lower()
        if "login" in current_url:
            return False
        page_source = driver.page_source.lower()
        indicators = ["logout", "退出", "注销", "登出", "个人信息", "my profile"]
        return any(ind in page_source for ind in indicators)
    except Exception:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
