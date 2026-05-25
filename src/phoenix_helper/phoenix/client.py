from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

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
        if config.cookie_header:
            self.session.headers.update({"Cookie": config.cookie_header})

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

        body, content_type = _build_multipart(data, upload_form.file_field, torrent_path.name, torrent_bytes)
        LOGGER.info("Multipart body size: %d bytes, Content-Type: %s", len(body), content_type)
        self._save_debug_bytes(body, "upload_request_body.bin")

        response = self.session.post(
            post_url,
            data=body,
            headers={"Content-Type": content_type},
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

    def _save_debug_bytes(self, data: bytes, filename: str) -> None:
        try:
            self.config.temp_dir.mkdir(parents=True, exist_ok=True)
            path = self.config.temp_dir / filename
            path.write_bytes(data)
            LOGGER.info("Debug binary saved: %s (%d bytes)", path, len(data))
        except Exception:
            LOGGER.exception("Failed to save debug binary %s", filename)


def _build_multipart(
    fields: dict[str, str],
    file_field_name: str,
    file_name: str,
    file_bytes: bytes,
) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    lines: list[bytes] = []
    for name, value in fields.items():
        lines.append(f"--{boundary}\r\n".encode())
        lines.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        lines.append(value.encode("utf-8"))
        lines.append(b"\r\n")
    lines.append(f"--{boundary}\r\n".encode())
    lines.append(
        f'Content-Disposition: form-data; name="{file_field_name}"; filename="{file_name}"\r\n'
        f"Content-Type: application/x-bittorrent\r\n\r\n".encode()
    )
    lines.append(file_bytes)
    lines.append(b"\r\n")
    lines.append(f"--{boundary}--\r\n".encode())
    body = b"".join(lines)
    content_type = f"multipart/form-data; boundary={boundary}"
    return body, content_type


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
