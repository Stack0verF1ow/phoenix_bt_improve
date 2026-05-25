"""Automate torrent upload via Selenium Edge browser.

Usage: python browser_upload.py <upload_url> <torrent_path> <title> <subtitle> <description> <category> <tags> [--profile-dir <dir>] [--headless]

Outputs detail_url and download_url on stdout on success.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.options import Options as EdgeOptions


def main() -> int:
    args = _parse_args()
    upload_url = args["upload_url"]
    torrent_path = args["torrent_path"]
    profile_dir = args["profile_dir"]
    headless = args["headless"]

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

    if profile_dir and Path(profile_dir).exists():
        options.add_argument(f"--user-data-dir={profile_dir}")
        options.add_argument("--profile-directory=Default")
        print(f"使用已保存的登录配置: {profile_dir}", file=sys.stderr)
    else:
        print("ERROR: 未找到登录配置，请先配置登录凭证。", file=sys.stderr)
        return 1

    print("正在启动浏览器...", file=sys.stderr)
    driver = webdriver.Edge(options=options)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })
    if not headless:
        driver.set_window_size(1280, 900)

    try:
        # Check login status
        if not _check_login(driver, upload_url):
            print("ERROR: 未登录，请先配置登录凭证。", file=sys.stderr)
            return 1

        print("已登录，开始上传...", file=sys.stderr)

        # Dismiss agreement overlay if present
        print("检查协议弹窗...", file=sys.stderr)
        driver.execute_script("""
            // Click agree button if visible
            var agree = document.getElementById('agree');
            if (agree) agree.click();
            // Ensure upload section is visible
            var upload = document.getElementById('upload');
            if (upload) upload.style.display = 'block';
        """)
        time.sleep(0.5)

        # Fill form fields using jQuery (required for jQuery Validate)
        title = args["title"]
        subtitle = args["subtitle"]
        description = args["description"]
        category = args["category"]
        tags = args["tags"]

        print("正在填写表单...", file=sys.stderr)
        result = driver.execute_script("""
            var title = arguments[0], subtitle = arguments[1], desc = arguments[2];
            var cat = arguments[3], tagStr = arguments[4];

            // Use jQuery .val() so jQuery Validate can read the values
            var $ = window.jQuery;
            if (!$) return 'no jQuery';

            var ok = 0;

            // Title (required)
            var $name = $('[name$="txtName"]').not('[name$="txtNameExtra"]');
            if ($name.length) { $name.val(title).trigger('input').trigger('change'); ok++; }

            // Subtitle
            var $extra = $('[name$="txtNameExtra"]');
            if ($extra.length) { $extra.val(subtitle).trigger('input').trigger('change'); ok++; }

            // Description (required)
            var $desc = $('[name$="txtDescription"]');
            if ($desc.length) { $desc.val(desc).trigger('input').trigger('change'); ok++; }

            // Category
            var $cat = $('[name$="ddlCategory"]');
            if ($cat.length) { $cat.val(cat).trigger('change'); ok++; }

            // Tags - use bootstrap-tagsinput plugin API
            var $tags = $('[name$="txtTags"]');
            if ($tags.length && tagStr) {
                var tagList = tagStr.split(/\\s+/).filter(function(t) { return t.length > 0; });
                tagList.forEach(function(tag) {
                    $tags.tagsinput('add', tag);
                });
                ok++;
            }

            return ok;
        """, title, subtitle, description, category, tags)
        print(f"已填写 {result} 个字段", file=sys.stderr)

        # Upload torrent file
        print("正在上传种子文件...", file=sys.stderr)
        # List all file inputs for debugging
        all_file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
        print(f"找到 {len(all_file_inputs)} 个文件上传控件", file=sys.stderr)
        for idx, fi in enumerate(all_file_inputs):
            name = fi.get_attribute("name") or "(no name)"
            print(f"  [{idx}] name={name}", file=sys.stderr)

        file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file'], input[name$='fuFile']")
        if not file_inputs:
            print("ERROR: 找不到文件上传控件", file=sys.stderr)
            return 1

        file_input = file_inputs[0]
        # Make the file input interactable
        driver.execute_script("""
            var el = arguments[0];
            el.style.display='block'; el.style.visibility='visible';
            el.style.opacity='1'; el.style.position='static';
            el.style.width='auto'; el.style.height='auto';
            el.removeAttribute('disabled');
        """, file_input)
        time.sleep(0.5)
        # Use forward slashes for send_keys compatibility
        abs_path = str(Path(torrent_path).resolve()).replace("\\", "/")
        print(f"上传文件路径: {abs_path}", file=sys.stderr)
        file_input.send_keys(abs_path)
        time.sleep(1)
        # Verify file was attached
        file_value = file_input.get_attribute("value") or ""
        print(f"文件控件值: {file_value}", file=sys.stderr)
        if not file_value:
            print("WARNING: 文件可能未成功附加", file=sys.stderr)

        # Click submit (use specific selector to avoid search button)
        print("正在提交...", file=sys.stderr)
        _dismiss_alerts(driver)
        submit_btn = driver.execute_script("""
            // Find the upload button specifically, not the search button
            var btn = document.querySelector('[name$="btnUpload"]');
            if (!btn) btn = document.querySelector('#upload input[type="submit"]');
            return btn;
        """)
        if submit_btn:
            driver.execute_script("arguments[0].scrollIntoView(true);", submit_btn)
            time.sleep(0.5)
            driver.execute_script("$(arguments[0]).click();", submit_btn)
        else:
            print("ERROR: 找不到提交按钮", file=sys.stderr)
            return 1

        # Wait for response
        print("等待服务器响应...", file=sys.stderr)
        time.sleep(5)
        _dismiss_alerts(driver)

        current_url = driver.current_url
        print(f"提交后页面: {current_url}", file=sys.stderr)

        if "error" in current_url.lower():
            print("ERROR: 服务器返回错误页面", file=sys.stderr)
            return 1

        # Find detail page
        detail_url = current_url if "detail" in current_url.lower() else ""
        if not detail_url:
            try:
                link = driver.find_element(By.CSS_SELECTOR, "a[href*='detail']")
                detail_url = link.get_attribute("href")
            except Exception:
                pass

        if not detail_url:
            print("ERROR: 无法找到详情页链接", file=sys.stderr)
            return 1

        print(f"详情页: {detail_url}", file=sys.stderr)

        # Navigate to detail page for download link
        if driver.current_url != detail_url:
            driver.get(detail_url)
            time.sleep(3)

        # Find torrent download link
        torrent_download_url = ""
        all_links = driver.find_elements(By.CSS_SELECTOR, "a[href]")
        for link in all_links:
            href = link.get_attribute("href") or ""
            text = link.text.strip()
            if "download" in href.lower() or ".torrent" in href.lower() or "下载" in text:
                print(f"  候选链接: {href} (text: {text})", file=sys.stderr)
                if not torrent_download_url:
                    torrent_download_url = href

        if not torrent_download_url:
            print("ERROR: 未找到种子下载链接", file=sys.stderr)
            return 1

        print(f"种子下载链接: {torrent_download_url}", file=sys.stderr)

        # Download torrent using Selenium's authenticated session via fetch API
        # urllib can't download because it doesn't have the login cookies
        print("正在通过浏览器下载种子...", file=sys.stderr)
        torrent_b64 = driver.execute_script("""
            var url = arguments[0];
            return fetch(url).then(function(r) { return r.blob(); })
                .then(function(blob) {
                    return new Promise(function(resolve) {
                        var reader = new FileReader();
                        reader.onloadend = function() { resolve(reader.result); };
                        reader.readAsDataURL(blob);
                    });
                });
        """, torrent_download_url)

        if not torrent_b64 or not torrent_b64.startswith("data:"):
            print("ERROR: 种子下载失败", file=sys.stderr)
            return 1

        # Decode base64 data
        import base64
        # Strip "data:application/x-bittorrent;base64," prefix
        b64_data = torrent_b64.split(",", 1)[1] if "," in torrent_b64 else torrent_b64
        torrent_bytes = base64.b64decode(b64_data)

        # Verify it's a valid torrent (bencode starts with 'd')
        if not torrent_bytes or torrent_bytes[0:1] != b'd':
            print(f"WARNING: 下载的内容可能不是种子文件 (前10字节: {torrent_bytes[:10]})", file=sys.stderr)

        # Save to temp file
        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix=".torrent", delete=False)
        tmp.write(torrent_bytes)
        tmp.close()
        print(f"种子已保存到: {tmp.name} ({len(torrent_bytes)} bytes)", file=sys.stderr)

        # Output: line 1 = detail_url, line 2 = saved torrent path
        print(detail_url)
        print(tmp.name)
        print("SUCCESS: 上传成功", file=sys.stderr)
        return 0

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    finally:
        driver.quit()


def _parse_args() -> dict:
    """Parse command line arguments."""
    positional = []
    kwargs = {"profile_dir": "", "headless": False}

    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "--profile-dir" and i + 1 < len(sys.argv):
            kwargs["profile_dir"] = sys.argv[i + 1]
            i += 2
        elif arg == "--headless":
            kwargs["headless"] = True
            i += 1
        else:
            positional.append(arg)
            i += 1

    if len(positional) < 7:
        print("Usage: browser_upload.py <upload_url> <torrent_path> <title> <subtitle> <description> <category> <tags> [--profile-dir <dir>] [--headless]", file=sys.stderr)
        sys.exit(1)

    keys = ["upload_url", "torrent_path", "title", "subtitle", "description", "category", "tags"]
    for k, v in zip(keys, positional):
        kwargs[k] = v
    return kwargs


def _check_login(driver: webdriver.Edge, upload_url: str) -> bool:
    """Check if logged in to the site."""
    driver.get(upload_url)
    time.sleep(3)
    _dismiss_alerts(driver)

    current_url = driver.current_url.lower()
    if "login" in current_url:
        return False

    page_source = driver.page_source.lower()
    indicators = ["logout", "退出", "注销", "登出", "个人信息", "my profile"]
    return any(ind in page_source for ind in indicators)


def _dismiss_alerts(driver: webdriver.Edge) -> None:
    for _ in range(3):
        try:
            alert = driver.switch_to.alert
            print(f"关闭弹窗: {alert.text[:50]}", file=sys.stderr)
            alert.dismiss()
            time.sleep(0.5)
        except Exception:
            break


if __name__ == "__main__":
    raise SystemExit(main())
