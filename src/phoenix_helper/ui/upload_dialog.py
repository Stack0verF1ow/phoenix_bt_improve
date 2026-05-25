from __future__ import annotations

import base64
import logging
from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtNetwork import QNetworkCookie
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from phoenix_helper.models import ResourceDraft

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
except ImportError:  # pragma: no cover
    QWebEngineView = None  # type: ignore[assignment]

LOGGER = logging.getLogger(__name__)


class UploadDialog(QDialog):
    upload_succeeded = Signal(str)
    upload_failed = Signal(str)

    def __init__(
        self,
        upload_url: str,
        draft: ResourceDraft,
        torrent_path: Path,
        cookie_header: str,
        parent: object | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("上传种子到金凤")
        self.resize(1024, 768)
        self._upload_url = upload_url
        self._draft = draft
        self._torrent_path = torrent_path
        self._cookie_header = cookie_header
        self._upload_page_injected = False
        self._result_emitted = False
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        if QWebEngineView is None:
            layout.addWidget(QLabel("当前打包缺少 QtWebEngine，无法使用浏览器上传。"))
            close_btn = QPushButton("关闭")
            close_btn.clicked.connect(self.reject)
            layout.addWidget(close_btn)
            return

        self._status_label = QLabel("正在加载上传页面...")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        self._web_view = QWebEngineView()
        layout.addWidget(self._web_view, 1)

        actions = QHBoxLayout()
        self._close_btn = QPushButton("关闭")
        self._close_btn.clicked.connect(self.reject)
        actions.addStretch(1)
        actions.addWidget(self._close_btn)
        layout.addLayout(actions)

        self._inject_cookies()
        self._web_view.loadFinished.connect(self._on_page_loaded)
        self._web_view.setUrl(QUrl(self._upload_url))

    def _inject_cookies(self) -> None:
        if not self._cookie_header:
            return
        store = self._web_view.page().profile().cookieStore()
        for pair in self._cookie_header.split(";"):
            pair = pair.strip()
            if "=" not in pair:
                continue
            name, _, value = pair.partition("=")
            cookie = QNetworkCookie()
            cookie.setName(name.strip().encode("utf-8"))
            cookie.setValue(value.strip().encode("utf-8"))
            cookie.setDomain("phoenix.stu.edu.cn")
            cookie.setPath("/")
            store.setCookie(cookie)

    def _on_page_loaded(self, ok: bool) -> None:
        if not ok:
            self._status_label.setText("页面加载失败。")
            return

        url = self._web_view.url().toString()
        path = self._web_view.url().path().lower()

        if "error.aspx" in path:
            self._status_label.setText("上传失败：服务器返回了错误页面。")
            if not self._result_emitted:
                self._result_emitted = True
                self.upload_failed.emit(url)
            return

        if "upload.aspx" in url.lower() and not self._upload_page_injected:
            self._upload_page_injected = True
            self._inject_form_data()
            return

        if "detail.aspx" in path and not self._result_emitted:
            self._result_emitted = True
            self._status_label.setText("上传成功！正在提取种子下载链接...")
            self._web_view.page().runJavaScript(
                "document.documentElement.outerHTML", 0, self._on_result_html
            )
            return

    def _inject_form_data(self) -> None:
        self._status_label.setText("正在预填表单并附加种子文件...")
        torrent_b64 = base64.b64encode(self._torrent_path.read_bytes()).decode("ascii")
        file_name = self._torrent_path.name

        js = _INJECT_JS.format(
            title=_js_string(self._draft.title),
            subtitle=_js_string(self._draft.subtitle),
            description=_js_string(self._draft.description),
            category=_js_string(self._draft.category),
            tags=_js_string(" ".join(self._draft.tags)),
            torrent_b64=torrent_b64,
            file_name=file_name,
        )
        self._web_view.page().runJavaScript(js, 0, self._on_inject_done)

    def _on_inject_done(self, result: object) -> None:
        self._status_label.setText(
            "表单已预填，种子已附加。请检查信息后点击页面上的「上传」按钮。"
        )

    def _on_result_html(self, html: object) -> None:
        html_str = str(html or "")
        detail_url = self._web_view.url().toString()
        torrent_url = _extract_torrent_url(html_str, detail_url)
        if torrent_url:
            self._status_label.setText(f"种子链接已找到：{torrent_url}")
            self.upload_succeeded.emit(torrent_url)
        else:
            self._status_label.setText(
                f"上传成功，但未找到种子下载链接。详情页：{detail_url}"
            )
            self.upload_succeeded.emit("")


def _js_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\r", "")
    return escaped


def _extract_torrent_url(html: str, base_url: str) -> str:
    from urllib.parse import urljoin

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"])
        if href.lower().endswith(".torrent"):
            return urljoin(base_url, href)
        if "download.ashx" in href.lower():
            return urljoin(base_url, href)
    return ""


_INJECT_JS = r"""
(function() {{
    function setVal(selector, value) {{
        var el = document.querySelector(selector);
        if (el) {{ el.value = value; }}
    }}

    var b64 = '{torrent_b64}';
    var raw = atob(b64);
    var bytes = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) {{
        bytes[i] = raw.charCodeAt(i);
    }}
    var file = new File([bytes], '{file_name}', {{type: 'application/x-bittorrent'}});

    var dt = new DataTransfer();
    dt.items.add(file);

    var fileInput = document.querySelector('input[type="file"]');
    if (fileInput) {{
        fileInput.files = dt.files;
        fileInput.dispatchEvent(new Event('change', {{bubbles: true}}));
    }}

    var nameInput = document.querySelector('input[id$="txtName"]');
    if (nameInput) {{ nameInput.value = '{title}'; }}

    var subtitleInput = document.querySelector('input[id$="txtNameExtra"]');
    if (subtitleInput) {{ subtitleInput.value = '{subtitle}'; }}

    var descInput = document.querySelector('textarea[id$="txtDescription"]');
    if (descInput) {{ descInput.value = '{description}'; }}

    var catSelect = document.querySelector('select[id$="ddlCategory"]');
    if (catSelect) {{ catSelect.value = '{category}'; }}
}})();
"""
