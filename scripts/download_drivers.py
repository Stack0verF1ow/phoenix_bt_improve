"""Download browser drivers for bundling into the exe.

Usage: python scripts/download_drivers.py

Downloads msedgedriver, chromedriver, geckodriver to scripts/drivers/
"""
from __future__ import annotations

import json
import os
import platform
import stat
import sys
import zipfile
import tarfile
from pathlib import Path
from urllib.request import urlretrieve

ROOT = Path(__file__).resolve().parents[1]
DRIVERS_DIR = ROOT / "scripts" / "drivers"


def main() -> int:
    DRIVERS_DIR.mkdir(parents=True, exist_ok=True)

    arch = "win64" if platform.machine().endswith("64") else "win32"
    print(f"平台: {sys.platform}, 架构: {arch}")

    # Download geckodriver (Firefox)
    print("\n=== geckodriver (Firefox) ===")
    _download_geckodriver()

    # Download chromedriver (Chrome)
    print("\n=== chromedriver (Chrome) ===")
    _download_chromedriver(arch)

    # msedgedriver is typically bundled with Edge on Windows
    # Selenium Manager handles it automatically, so we skip downloading
    print("\n=== msedgedriver (Edge) ===")
    print("Edge driver 由系统自动管理，跳过下载。")

    print(f"\n驱动已下载到: {DRIVERS_DIR}")
    return 0


def _download_geckodriver():
    """Download latest geckodriver release."""
    import subprocess
    try:
        # Get latest release info from GitHub API
        import requests
        resp = requests.get(
            "https://api.github.com/repos/mozilla/geckodriver/releases/latest",
            timeout=15,
        )
        data = resp.json()
        version = data["tag_name"]
        print(f"最新版本: {version}")

        # Find win64 zip asset
        asset_url = None
        for asset in data.get("assets", []):
            name = asset["name"]
            if "win64" in name and name.endswith(".zip"):
                asset_url = asset["browser_download_url"]
                break

        if not asset_url:
            print("未找到 win64 资产，跳过。")
            return

        zip_path = DRIVERS_DIR / "geckodriver.zip"
        print(f"下载: {asset_url}")
        _download_file(asset_url, zip_path)

        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(DRIVERS_DIR)
        zip_path.unlink()
        print(f"已解压到: {DRIVERS_DIR / 'geckodriver.exe'}")
    except Exception as e:
        print(f"下载失败: {e}")


def _download_chromedriver(arch: str):
    """Download chromedriver matching installed Chrome version."""
    import subprocess
    try:
        # Get installed Chrome version
        chrome_version = _get_chrome_version()
        if not chrome_version:
            print("未检测到 Chrome，跳过。")
            return
        print(f"已安装 Chrome: {chrome_version}")

        major = chrome_version.split(".")[0]

        # For Chrome 115+, use Chrome for Testing API
        if int(major) >= 115:
            _download_chromedriver_cft(major, arch)
        else:
            _download_chromedriver_legacy(chrome_version, arch)
    except Exception as e:
        print(f"下载失败: {e}")


def _download_chromedriver_cft(major: str, arch: str):
    """Download chromedriver from Chrome for Testing API (Chrome 115+)."""
    import requests

    # Get known good versions
    resp = requests.get(
        f"https://googlechromelabs.github.io/chrome-for-testing/known-good-versions-with-downloads.json",
        timeout=15,
    )
    data = resp.json()

    # Find latest version matching major
    driver_url = None
    for version_info in reversed(data["versions"]):
        if version_info["version"].startswith(major + "."):
            downloads = version_info.get("downloads", {}).get("chromedriver", [])
            for dl in downloads:
                if dl["platform"] == "win64" if arch == "win64" else "win32":
                    driver_url = dl["url"]
                    break
            if driver_url:
                break

    if not driver_url:
        print(f"未找到 Chrome {major} 对应的 driver。")
        return

    zip_path = DRIVERS_DIR / "chromedriver.zip"
    print(f"下载: {driver_url}")
    _download_file(driver_url, zip_path)

    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if name.endswith("chromedriver.exe"):
                # Extract to flat directory
                with zf.open(name) as src:
                    target = DRIVERS_DIR / "chromedriver.exe"
                    target.write_bytes(src.read())
                break
    zip_path.unlink()
    print(f"已解压到: {DRIVERS_DIR / 'chromedriver.exe'}")


def _download_chromedriver_legacy(chrome_version: str, arch: str):
    """Download chromedriver for Chrome < 115."""
    import requests

    major = chrome_version.split(".")[0]
    url = f"https://chromedriver.storage.googleapis.com/LATEST_RELEASE_{major}"
    resp = requests.get(url, timeout=15)
    driver_version = resp.text.strip()
    print(f"Driver 版本: {driver_version}")

    zip_url = f"https://chromedriver.storage.googleapis.com/{driver_version}/chromedriver_win64.zip"
    zip_path = DRIVERS_DIR / "chromedriver.zip"
    print(f"下载: {zip_url}")
    _download_file(zip_url, zip_path)

    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if name.endswith("chromedriver.exe"):
                with zf.open(name) as src:
                    target = DRIVERS_DIR / "chromedriver.exe"
                    target.write_bytes(src.read())
                break
    zip_path.unlink()
    print(f"已解压到: {DRIVERS_DIR / 'chromedriver.exe'}")


def _get_chrome_version() -> str | None:
    """Get installed Chrome version on Windows."""
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Google\Chrome\BLBeacon")
        version, _ = winreg.QueryValueEx(key, "version")
        return version
    except Exception:
        pass

    # Try common paths
    for path in [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]:
        if Path(path).exists():
            # Get version from file
            import subprocess
            result = subprocess.run(
                ["wmic", "datafile", "where", f"name='{path}'", "get", "Version", "/value"],
                capture_output=True, text=True, timeout=10,
            )
            for line in result.stdout.splitlines():
                if line.startswith("Version="):
                    return line.split("=", 1)[1].strip()
    return None


def _download_file(url: str, target: Path):
    """Download a file with progress."""
    import requests
    resp = requests.get(url, stream=True, timeout=60)
    resp.raise_for_status()
    total = int(resp.headers.get("content-length", 0))
    downloaded = 0
    with open(target, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
            downloaded += len(chunk)
            if total:
                pct = downloaded * 100 // total
                print(f"\r  {downloaded // 1024}KB / {total // 1024}KB ({pct}%)", end="", flush=True)
    print()


if __name__ == "__main__":
    raise SystemExit(main())
