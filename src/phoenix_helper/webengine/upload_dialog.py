"""WebEngine-based upload dialog that automates filling and submitting the Phoenix upload form."""

from __future__ import annotations

import base64
import logging
from pathlib import Path

from PySide6.QtCore import QUrl, Qt, QTimer
from PySide6.QtNetwork import QNetworkCookie
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from phoenix_helper.models import ResourceDraft

LOGGER = logging.getLogger(__name__)

_INJECT_AND_SUBMIT_JS = r"""
(function() {{
    function setVal(selector, value) {{
        var el = document.querySelector(selector);
        if (el) {{ el.value = value; }}
    }}

    // Set torrent file via DataTransfer API
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

    // Fill form fields
    var nameInput = document.querySelector('input[id$="txtName"]');
    if (nameInput) {{ nameInput.value = '{title}'; }}

    var subtitleInput = document.querySelector('input[id$="txtNameExtra"]');
    if (subtitleInput) {{ subtitleInput.value = '{subtitle}'; }}

    var descInput = document.querySelector('textarea[id$="txtDescription"]');
    if (descInput) {{ descInput.value = '{description}'; }}

    var catSelect = document.querySelector('select[id$="ddlCategory"]');
    if (catSelect) {{ catSelect.value = '{category}'; }}

    // Auto-click upload button after a short delay
    setTimeout(function() {{
        var submitBtn = document.querySelector('input[id$="btnUpload"]');
        if (submitBtn) {{
            submitBtn.click();
        }}
    }}, 500);

    return 'OK';
}})();
"""

_JS_FIND_TORRENT = r"""
(function() {{
    var links = document.querySelectorAll('a[href]');
    for (var i = 0; i < links.length; i++) {{
        var href = links[i].href.toLowerCase();
        if (href.endsWith('.torrent') || href.indexOf('download.ashx') !== -1) {{
            return links[i].href;
        }}
    }}
    return '';
}})();
"""


def _js_string(value: str) -> str:
    """Escape a Python string for embedding in JS."""
    return value.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\r", "")


class WebEngineUploadDialog(QDialog):
    """Embedded browser dialog that automates filling and submitting the Phoenix upload form."""

    def __init__(
        self,
        site_base_url: str,
        draft: ResourceDraft,
        torrent_path: Path,
        cookie_header: str = "",
        show_window: bool = True,
        parent: object | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("金凤上传")
        self.resize(900, 650)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint)

        self.site_base_url = site_base_url.rstrip("/")
        self.draft = draft
        self.torrent_path = torrent_path
        self._cookie_header = cookie_header
        self._show_window = show_window
        self._detail_url = ""
        self._torrent_url = ""
        self._upload_success = False
        self._form_injected = False
        self._auto_closed = False

        self._profile = QWebEngineProfile("phoenix_upload")
        self._profile.setPersistentStoragePath(str(Path.home() / ".phoenix_helper" / "webengine_profile"))
        self._profile.setPersistentCookiesPolicy(QWebEngineProfile.ForcePersistentCookies)
        self._profile.setParent(self)

        self._page = QWebEnginePage(self._profile, self)
        self._view = QWebEngineView()
        self._view.setPage(self._page)
        self._view.loadFinished.connect(self._on_page_loaded)

        self._build_ui()
        self._inject_cookies()

        # When not showing the window, move it off-screen instead of hiding it.
        # Calling hide() on a modal QDialog (opened with exec()) ends the modal
        # event loop immediately, causing the upload to be cancelled.
        if not self._show_window:
            self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
            self.move(-10000, -10000)
            self.resize(1, 1)

        self._view.load(QUrl(f"{self.site_base_url}/BT/upload.aspx"))

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self._status_label = QLabel("正在加载上传页面...")
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet("font-size: 14px; padding: 8px;")
        layout.addWidget(self._status_label)

        layout.addWidget(self._view, 1)

        btn_layout = QHBoxLayout()
        self._cancel_btn = QPushButton("取消")
        self._cancel_btn.clicked.connect(self.reject)

        self._done_btn = QPushButton("完成")
        self._done_btn.clicked.connect(self._on_done)
        self._done_btn.setEnabled(False)

        btn_layout.addStretch(1)
        btn_layout.addWidget(self._cancel_btn)
        btn_layout.addWidget(self._done_btn)
        layout.addLayout(btn_layout)

    @property
    def detail_url(self) -> str:
        return self._detail_url

    @property
    def torrent_url(self) -> str:
        return self._torrent_url

    def _inject_cookies(self) -> None:
        """Inject cookies into the WebEngine profile."""
        if not self._cookie_header:
            return
        store = self._profile.cookieStore()
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
            LOGGER.debug("Set cookie: %s", name.strip())

    def _on_page_loaded(self, ok: bool) -> None:
        """Handle page load completion."""
        if not ok:
            self._set_error("页面加载失败，请检查网络连接。")
            return

        url = self._view.url().toString()
        path = self._view.url().path().lower()
        LOGGER.info("Page loaded: %s", url)

        # Check for error page
        if "error.aspx" in path:
            self._set_error("服务器返回错误页面。")
            return

        # Upload page - inject form data and auto-submit
        if "upload.aspx" in url.lower() and not self._form_injected:
            self._form_injected = True
            self._inject_form_data()
            return

        # Detail page - upload succeeded
        if "detail.aspx" in path and not self._upload_success:
            self._upload_success = True
            self._detail_url = url
            self._set_status("上传成功！正在获取种子链接...")
            self._page.runJavaScript(_JS_FIND_TORRENT, 0, self._on_torrent_found)
            return

    def _inject_form_data(self) -> None:
        """Inject form data and torrent file using JavaScript, then auto-submit."""
        self._set_status("正在填写表单并上传...")

        torrent_b64 = base64.b64encode(self.torrent_path.read_bytes()).decode("ascii")
        file_name = self.torrent_path.name

        js = _INJECT_AND_SUBMIT_JS.format(
            title=_js_string(self.draft.title),
            subtitle=_js_string(self.draft.subtitle),
            description=_js_string(self.draft.description),
            category=_js_string(self.draft.category),
            tags=_js_string(" ".join(self.draft.tags)),
            torrent_b64=torrent_b64,
            file_name=file_name,
        )

        LOGGER.info("Injecting form and auto-submitting: title=%r, category=%r, file=%s",
                     self.draft.title, self.draft.category, file_name)

        self._page.runJavaScript(js, 0, self._on_form_injected)

    def _on_form_injected(self, result: object) -> None:
        """Handle form injection completion."""
        LOGGER.info("Form injection result: %s", result)
        self._set_status("正在上传，请等待...")

    def _on_torrent_found(self, torrent_url: object) -> None:
        """Handle torrent URL found."""
        torrent_str = str(torrent_url or "")
        if torrent_str:
            self._torrent_url = torrent_str
            LOGGER.info("Torrent URL found: %s", torrent_str)
            self._set_status("上传完成！")
        else:
            LOGGER.warning("No torrent URL found on detail page")
            self._set_status("上传成功，但未找到种子下载链接。")

        self._done_btn.setEnabled(True)

        # Auto-close dialog and proceed with download
        if not self._auto_closed:
            self._auto_closed = True
            QTimer.singleShot(500, self.accept)

    def _set_status(self, message: str) -> None:
        """Update status label."""
        self._status_label.setText(message)
        self._status_label.setStyleSheet("color: #1565C0; font-weight: bold; font-size: 14px; padding: 8px;")

    def _set_error(self, message: str) -> None:
        """Show error message."""
        self._status_label.setText(f"错误：{message}")
        self._status_label.setStyleSheet("color: #E65100; font-weight: bold; font-size: 14px; padding: 8px;")
        self._done_btn.setEnabled(True)

        # Auto-close on error
        if not self._auto_closed:
            self._auto_closed = True
            QTimer.singleShot(500, self.reject)

    def _on_done(self) -> None:
        """Handle done button."""
        if self._upload_success:
            self.accept()
        else:
            self.reject()

    # No showEvent override needed: when not showing the window, the dialog is
    # positioned off-screen in __init__ rather than hidden, because hide()
    # on a modal dialog ends the exec() event loop prematurely.
