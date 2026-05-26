"""Test HTTP login flow. Set PHOENIX_USER and PHOENIX_PASS env vars first."""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
LOGGER = logging.getLogger("test_login")

BASE = "http://phoenix.stu.edu.cn"
LOGIN_URL = f"{BASE}/login.aspx"


def login(username: str, password: str) -> requests.Session | None:
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })

    # Step 1: GET login page for ASP.NET hidden fields
    LOGGER.info("Fetching login page...")
    r = session.get(LOGIN_URL, timeout=10)
    LOGGER.info("GET login: status=%d, url=%s", r.status_code, r.url)
    if r.status_code != 200:
        LOGGER.error("Failed to fetch login page")
        return None

    soup = BeautifulSoup(r.text, "html.parser")
    form = soup.find("form")
    if not form:
        LOGGER.error("No form found on login page")
        return None

    fields = {}
    for inp in form.find_all("input"):
        name = inp.get("name", "")
        if name and inp.get("type", "") == "hidden":
            fields[name] = inp.get("value", "")
    LOGGER.info("Hidden fields: %s", list(fields.keys()))

    # Step 2: POST login
    fields["ctl00$cpContent$txtName"] = username
    fields["ctl00$cpContent$txtPass"] = password
    fields["ctl00$cpContent$chkRememberMe"] = "on"
    fields["ctl00$cpContent$btnLogin"] = "登录"

    LOGGER.info("POST login as %s...", username)
    r2 = session.post(LOGIN_URL, data=fields, timeout=10)
    LOGGER.info("POST login: status=%d, url=%s", r2.status_code, r2.url)

    # Step 3: Check if redirected away from login page
    if "login.aspx" not in r2.url.lower():
        LOGGER.info("LOGIN SUCCESS! Redirected to: %s", r2.url)
        LOGGER.info("Cookies:")
        auth_cookie = None
        for cookie in session.cookies:
            value_preview = str(cookie.value)[:40]
            LOGGER.info("  %s = %s...", cookie.name, value_preview)
            if "funSTU" in cookie.name or "auth" in cookie.name.lower():
                auth_cookie = cookie
        LOGGER.info("Auth cookie: %s", auth_cookie.name if auth_cookie else "NOT FOUND")
        return session
    else:
        LOGGER.warning("Still on login page - login failed")
        # Check error message
        for sel in ("#cpContent__cphContent_lblInfo", ".validation-summary-errors"):
            el = BeautifulSoup(r2.text, "html.parser").select_one(sel)
            if el:
                text = el.get_text(strip=True)
                if text:
                    LOGGER.warning("Error message: %s", text)
        return None


def main() -> int:
    username = os.environ.get("PHOENIX_USER") or input("Username: ")
    import getpass
    password = os.environ.get("PHOENIX_PASS") or getpass.getpass("Password: ")

    result = login(username, password)
    if result is not None:
        # Verify by fetching the upload page
        LOGGER.info("Verifying: fetching upload page...")
        r = result.get(f"{BASE}/BT/upload.aspx", timeout=10)
        if "upload.aspx" in r.url.lower():
            LOGGER.info("Upload page accessible!")
            # Extract quota for extra verification
            idx = r.text.find("lblCountUpload")
            if idx > 0:
                start = r.text.find(">", idx) + 1
                end = r.text.find("<", start)
                quota = r.text[start:end].strip() if start > 0 and end > start else "?"
                LOGGER.info("Quota: %s", quota)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
