from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

from bs4 import BeautifulSoup

from phoenix_helper.config import AppConfig
from phoenix_helper.models import ResourceDraft, UploadResult
from phoenix_helper.phoenix.forms import UploadForm, parse_upload_form
from phoenix_helper.phoenix.parser import (
    extract_error_message,
    extract_error_page_message,
    find_detail_url,
    find_torrent_url,
)
from phoenix_helper.utils.paths import safe_filename, unique_path

LOGGER = logging.getLogger(__name__)


class PhoenixClientError(RuntimeError):
    pass


class PhoenixClient:
    def __init__(self, config: AppConfig, session: requests.Session | None = None) -> None:
        self.config = config
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        })
        if config.cookie_header:
            for pair in config.cookie_header.split(";"):
                pair = pair.strip()
                if "=" not in pair:
                    continue
                name, value = pair.split("=", 1)
                self.session.cookies.set(
                    name.strip(), value.strip(),
                    domain="phoenix.stu.edu.cn", path="/",
                )

    LOGIN_URL_PATH = "/login.aspx"

    def login(self, username: str, password: str) -> str:
        """Login to the Phoenix site via HTTP. Returns the auth cookie header."""
        login_url = f"{self.config.site_base_url.rstrip('/')}{self.LOGIN_URL_PATH}"
        LOGGER.info("GET login page: %s", login_url)
        r = self.session.get(login_url, timeout=20)
        r.raise_for_status()
        LOGGER.info("Login page: status=%d, url=%s", r.status_code, r.url)

        if "login.aspx" not in r.url.lower():
            LOGGER.warning("Already logged in, redirect: %s", r.url)
            # Already logged in, return existing cookie header
            return self._get_cookie_header()

        soup = BeautifulSoup(r.text, "html.parser")
        form = soup.find("form")
        if not form:
            raise PhoenixClientError("Login form not found")

        fields = {}
        for inp in form.find_all("input"):
            name = inp.get("name", "")
            if name and inp.get("type", "") == "hidden":
                fields[name] = inp.get("value", "")

        fields["ctl00$cpContent$txtName"] = username
        fields["ctl00$cpContent$txtPass"] = password
        fields["ctl00$cpContent$chkRememberMe"] = "on"
        fields["ctl00$cpContent$btnLogin"] = "登录"

        LOGGER.info("POST login as %s...", username)
        r2 = self.session.post(login_url, data=fields, timeout=20)
        LOGGER.info("POST login: status=%d, url=%s", r2.status_code, r2.url)

        if "login.aspx" not in r2.url.lower():
            LOGGER.info("Login successful! Redirected to: %s", r2.url)
            cookie_header = self._get_cookie_header()
            LOGGER.info("Auth cookie captured (%d chars)", len(cookie_header))
            return cookie_header

        LOGGER.warning("Login failed - still on login page")
        error = ""
        for sel in ("#cpContent__cphContent_lblInfo", ".validation-summary-errors"):
            el = BeautifulSoup(r2.text, "html.parser").select_one(sel)
            if el:
                error = el.get_text(strip=True)
                if error:
                    break
        raise PhoenixClientError(error or "登录失败，请检查用户名和密码")

    def _get_cookie_header(self) -> str:
        """Build cookie header string from session cookie jar."""
        cookies = []
        for cookie in self.session.cookies:
            if "phoenix" in cookie.domain or "stu.edu.cn" in cookie.domain:
                cookies.append(f"{cookie.name}={cookie.value}")
        return "; ".join(cookies)

    def fetch_upload_form(self) -> UploadForm:
        LOGGER.info("GET upload form: %s", self.config.upload_url)
        response = self.session.get(self.config.upload_url, timeout=20)
        response.raise_for_status()
        LOGGER.info("Upload form status=%d, url=%s", response.status_code, response.url)
        return parse_upload_form(response.text, self.config.site_base_url)

    def upload_torrent(self, draft: ResourceDraft, torrent_path: Path) -> UploadResult:
        upload_form = self.fetch_upload_form()
        post_url = urljoin(self.config.upload_url, upload_form.action or self.config.upload_url)
        data = dict(upload_form.fields)
        data[upload_form.title_field] = draft.title
        data[upload_form.subtitle_field] = draft.subtitle
        data[upload_form.description_field] = draft.description
        data[upload_form.category_field] = draft.category
        if upload_form.tags_field is not None:
            data[upload_form.tags_field] = " ".join(draft.tags)
        if upload_form.tags_fid_field is not None:
            data[upload_form.tags_fid_field] = "0"
        if upload_form.submit_field is not None:
            data[upload_form.submit_field] = "上传"

        LOGGER.info("POST upload: %s", post_url)
        LOGGER.info("Form fields: %s", list(data.keys()))
        LOGGER.info("Title=%r, Category=%r, Tags=%r", draft.title, draft.category, draft.tags)

        torrent_bytes = torrent_path.read_bytes()
        LOGGER.info("Torrent file: %s (%d bytes)", torrent_path.name, len(torrent_bytes))

        files = {
            upload_form.file_field: (torrent_path.name, torrent_bytes, "application/x-bittorrent"),
        }
        LOGGER.info("POST fields: %d, file field: %s", len(data), upload_form.file_field)

        headers = {
            "Referer": self.config.upload_url,
            "Origin": self.config.site_base_url,
        }
        response = self.session.post(
            post_url,
            data=data,
            files=files,
            headers=headers,
            timeout=60,
        )
        response.raise_for_status()

        LOGGER.info("Upload response: status=%d, url=%s", response.status_code, response.url)
        self._save_debug_html(response.text, "upload_response.html")

        error = extract_error_message(response.text)

        if _is_error_url(response.url):
            error = self._fetch_error_page_message(response.url) or "上传失败，服务器返回了错误页面。"
            LOGGER.warning("Server redirected to error page: %s", response.url)
            return UploadResult(False, error, detail_url="", torrent_url="")

        if error:
            LOGGER.warning("Upload error from page: %s", error)
            return UploadResult(False, error, detail_url="", torrent_url="")

        detail_url = self._resolve_detail_url(response.text, response.url)

        if _same_url(response.url, self.config.upload_url) and not detail_url:
            error = (
                "上传后页面仍停留在上传页，服务器可能拒绝了请求。"
                "请检查上传响应 HTML（已保存到 upload_response.html）确认原因。"
            )
            LOGGER.warning("Response URL same as upload URL — possible silent rejection")
            return UploadResult(False, error, detail_url="", torrent_url="")

        torrent_url = find_torrent_url(response.text, detail_url or self.config.site_base_url)
        if detail_url and not torrent_url:
            LOGGER.info("No torrent link in POST response, fetching detail page: %s", detail_url)
            detail_response = self.session.get(detail_url, timeout=20)
            detail_response.raise_for_status()
            LOGGER.info("Detail page status=%d, url=%s", detail_response.status_code, detail_response.url)
            self._save_debug_html(detail_response.text, "detail_response.html")

            if _is_error_url(detail_response.url):
                error = self._fetch_error_page_message(detail_response.url) or "详情页返回了错误。"
                LOGGER.warning("Detail page is an error page: %s", detail_response.url)
                return UploadResult(False, error, detail_url=detail_url, torrent_url="")

            torrent_url = find_torrent_url(detail_response.text, detail_url)
            if not torrent_url:
                LOGGER.warning("Still no torrent link on detail page")

        return UploadResult(True, "上传完成", detail_url=detail_url, torrent_url=torrent_url)

    def fetch_torrent_url_from_detail(self, detail_url: str) -> str:
        """Fetch the detail page and extract the torrent download URL."""
        LOGGER.info("Fetching detail page: %s", detail_url)
        response = self.session.get(detail_url, timeout=20)
        response.raise_for_status()
        LOGGER.info("Detail page status=%d, url=%s", response.status_code, response.url)
        self._save_debug_html(response.text, "detail_response.html")

        if _is_error_url(response.url):
            error = self._fetch_error_page_message(response.url) or "详情页返回了错误。"
            raise PhoenixClientError(error)

        torrent_url = find_torrent_url(response.text, detail_url)
        if torrent_url:
            LOGGER.info("Found torrent URL: %s", torrent_url)
        else:
            LOGGER.warning("No torrent URL found on detail page")
        return torrent_url

    def download_final_torrent(self, torrent_url: str, title: str, save_dir: Path | None = None) -> Path:
        if not torrent_url:
            raise PhoenixClientError("final torrent URL is empty")
        LOGGER.info("Downloading final torrent: %s", torrent_url)
        target_dir = save_dir or self.config.final_torrent_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        response = self.session.get(torrent_url, timeout=30)
        response.raise_for_status()
        LOGGER.info("Final torrent download: status=%d, content-length=%s",
                     response.status_code, response.headers.get("Content-Length", "unknown"))
        filename = safe_filename(title) + ".torrent"
        target = unique_path(target_dir / filename)
        target.write_bytes(response.content)
        LOGGER.info("Final torrent saved: %s (%d bytes)", target, len(response.content))
        return target

    def _resolve_detail_url(self, html: str, response_url: str) -> str:
        # If the response already landed on the detail page, use it directly
        if response_url and "detail.aspx" in response_url.lower():
            return response_url
        detail_url = find_detail_url(html, self.config.site_base_url)
        if detail_url:
            return detail_url
        if response_url and not _same_url(response_url, self.config.upload_url) and not _is_error_url(response_url):
            return response_url
        return ""

    def _fetch_error_page_message(self, error_url: str) -> str:
        try:
            LOGGER.info("Fetching error page: %s", error_url)
            resp = self.session.get(error_url, timeout=20)
            resp.raise_for_status()
            self._save_debug_html(resp.text, "error_page.html")
            message = extract_error_page_message(resp.text)
            LOGGER.info("Error page message: %s", message[:200] if message else "(empty)")
            return message
        except Exception:
            LOGGER.exception("Failed to fetch error page")
            return ""

    def _save_debug_html(self, html: str, filename: str) -> None:
        try:
            self.config.temp_dir.mkdir(parents=True, exist_ok=True)
            path = self.config.temp_dir / filename
            path.write_text(html, encoding="utf-8")
            LOGGER.info("Debug HTML saved: %s (%d chars)", path, len(html))
        except Exception:
            LOGGER.exception("Failed to save debug HTML %s", filename)



def _same_url(left: str, right: str) -> bool:
    left_parts = urlparse(left)
    right_parts = urlparse(right)
    return (
        left_parts.scheme.lower(),
        left_parts.netloc.lower(),
        left_parts.path.rstrip("/"),
    ) == (
        right_parts.scheme.lower(),
        right_parts.netloc.lower(),
        right_parts.path.rstrip("/"),
    )


def _is_error_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return "error" in path
