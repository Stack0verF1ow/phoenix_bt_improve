"""Shared WebDriver factory for Edge/Chrome/Firefox."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Show Selenium Manager download progress
os.environ.setdefault("SE_MANAGER_LOG_LEVEL", "info")

from selenium import webdriver
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.firefox.service import Service as FirefoxService


def _get_drivers_dir() -> Path | None:
    """Find the bundled drivers directory."""
    # PyInstaller bundled exe
    if hasattr(sys, "_MEIPASS"):
        candidates = [
            Path(sys._MEIPASS) / "scripts" / "drivers",
            Path(sys._MEIPASS) / "drivers",
        ]
    else:
        # Running from source
        script_dir = Path(__file__).resolve().parent
        candidates = [
            script_dir / "drivers",
        ]
    for p in candidates:
        if p.is_dir():
            return p
    return None


def _find_driver(drivers_dir: Path | None, name: str) -> str | None:
    """Return path to bundled driver exe if it exists."""
    if drivers_dir is None:
        return None
    exe = drivers_dir / name
    if exe.is_file():
        return str(exe)
    return None


def create_driver(browser: str, profile_dir: str, headless: bool = False):
    """Create a Selenium WebDriver for the specified browser.

    Args:
        browser: "edge", "chrome", or "firefox"
        profile_dir: path to persistent profile directory
        headless: run in headless mode
    """
    browser = browser.lower().strip()
    drivers_dir = _get_drivers_dir()

    if browser == "chrome":
        return _create_chrome(profile_dir, headless, drivers_dir)
    elif browser == "firefox":
        return _create_firefox(profile_dir, headless, drivers_dir)
    else:
        return _create_edge(profile_dir, headless, drivers_dir)


def _create_edge(profile_dir: str, headless: bool, drivers_dir: Path | None) -> webdriver.Edge:
    options = EdgeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-features=msEdgeSidebarV2,msEdgeCopilot")
    options.add_argument("--disable-extensions")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1280,900")

    if profile_dir:
        options.add_argument(f"--user-data-dir={profile_dir}")
        options.add_argument("--profile-directory=Default")

    driver_path = _find_driver(drivers_dir, "msedgedriver.exe")
    service = EdgeService(executable_path=driver_path) if driver_path else EdgeService()

    driver = webdriver.Edge(service=service, options=options)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    if not headless:
        driver.set_window_size(1280, 900)
    return driver


def _create_chrome(profile_dir: str, headless: bool, drivers_dir: Path | None) -> webdriver.Chrome:
    options = ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-extensions")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1280,900")

    if profile_dir:
        options.add_argument(f"--user-data-dir={profile_dir}")
        options.add_argument("--profile-directory=Default")

    driver_path = _find_driver(drivers_dir, "chromedriver.exe")
    service = ChromeService(executable_path=driver_path) if driver_path else ChromeService()

    driver = webdriver.Chrome(service=service, options=options)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    if not headless:
        driver.set_window_size(1280, 900)
    return driver


def _create_firefox(profile_dir: str, headless: bool, drivers_dir: Path | None) -> webdriver.Firefox:
    options = FirefoxOptions()

    if headless:
        options.add_argument("--headless")

    if profile_dir:
        options.add_argument("-profile")
        options.add_argument(profile_dir)

    driver_path = _find_driver(drivers_dir, "geckodriver.exe")
    service = FirefoxService(executable_path=driver_path) if driver_path else FirefoxService()

    driver = webdriver.Firefox(service=service, options=options)
    if not headless:
        driver.set_window_size(1280, 900)
    return driver
