"""Open Edge browser for user to log in to phoenix site. Saves cookies to persistent profile.

Usage: python browser_login.py <site_url> <profile_dir>

Exits 0 on success, 1 on failure.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.options import Options as EdgeOptions


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: browser_login.py <site_url> <profile_dir>", file=sys.stderr)
        return 1

    site_url = sys.argv[1]
    profile_dir = sys.argv[2]

    Path(profile_dir).mkdir(parents=True, exist_ok=True)

    options = EdgeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-features=msEdgeSidebarV2,msEdgeCopilot")
    options.add_argument("--disable-extensions")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument(f"--user-data-dir={profile_dir}")
    options.add_argument("--profile-directory=Default")

    print("正在启动浏览器...", file=sys.stderr)
    driver = webdriver.Edge(options=options)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    driver.set_window_size(1280, 900)

    try:
        parsed = urlparse(site_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        login_url = f"{base_url}/login.aspx"

        # Directly open the login page
        driver.get(login_url)
        time.sleep(2)

        print("请在浏览器窗口中登录金凤网站...", file=sys.stderr)
        print("登录成功后会自动检测并保存凭证。", file=sys.stderr)

        # Wait for login: only check URL and page content, never navigate away
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


def _is_logged_in(driver: webdriver.Edge, base_url: str) -> bool:
    """Check if logged in by looking at the current URL and page content.

    Does NOT navigate to avoid interrupting user input.
    """
    try:
        current_url = driver.current_url.lower()

        # If still on login page, user hasn't logged in yet
        if "login" in current_url:
            return False

        # If redirected away from login, check for logged-in indicators
        page_source = driver.page_source.lower()
        indicators = ["logout", "退出", "注销", "登出", "个人信息", "my profile"]
        return any(ind in page_source for ind in indicators)
    except Exception:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
