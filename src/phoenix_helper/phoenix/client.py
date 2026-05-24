from __future__ import annotations

from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

from phoenix_helper.config import AppConfig
from phoenix_helper.models import ResourceDraft, UploadResult
from phoenix_helper.phoenix.forms import UploadForm, parse_upload_form
from phoenix_helper.phoenix.parser import extract_error_message, find_detail_url, find_torrent_url
from phoenix_helper.utils.paths import safe_filename, unique_path


class PhoenixClientError(RuntimeError):
    pass


class PhoenixClient:
    def __init__(self, config: AppConfig, session: requests.Session | None = None) -> None:
        self.config = config
        self.session = session or requests.Session()
        if config.cookie_header:
            self.session.headers.update({"Cookie": config.cookie_header})

    def fetch_upload_form(self) -> UploadForm:
        response = self.session.get(self.config.upload_url, timeout=20)
        response.raise_for_status()
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
        if upload_form.submit_field is not None:
            data[upload_form.submit_field] = "上传"

        with torrent_path.open("rb") as torrent_file:
            files = {
                upload_form.file_field: (
                    torrent_path.name,
                    torrent_file,
                    "application/x-bittorrent",
                )
            }
            response = self.session.post(post_url, data=data, files=files, timeout=60)
        response.raise_for_status()

        error = extract_error_message(response.text)
        detail_url = self._resolve_detail_url(response.text, response.url)
        torrent_url = find_torrent_url(response.text, detail_url or self.config.site_base_url)
        if not error and detail_url and not torrent_url:
            detail_response = self.session.get(detail_url, timeout=20)
            detail_response.raise_for_status()
            torrent_url = find_torrent_url(detail_response.text, detail_url)
        if error:
            return UploadResult(False, error, detail_url=detail_url, torrent_url=torrent_url)
        return UploadResult(True, "上传完成", detail_url=detail_url, torrent_url=torrent_url)

    def download_final_torrent(self, torrent_url: str, title: str) -> Path:
        if not torrent_url:
            raise PhoenixClientError("final torrent URL is empty")
        self.config.final_torrent_dir.mkdir(parents=True, exist_ok=True)
        response = self.session.get(torrent_url, timeout=30)
        response.raise_for_status()
        filename = safe_filename(title) + ".torrent"
        target = unique_path(self.config.final_torrent_dir / filename)
        target.write_bytes(response.content)
        return target

    def _resolve_detail_url(self, html: str, response_url: str) -> str:
        detail_url = find_detail_url(html, self.config.site_base_url)
        if detail_url:
            return detail_url
        if response_url and not _same_url(response_url, self.config.upload_url):
            return response_url
        return ""


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
