"""WebEngine-based login dialog for Phoenix site authentication."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QUrl, Qt, QTimer, QEventLoop
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineCookieStore
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

LOGGER = logging.getLogger(__name__)

WEBENGINE_PROFILE_DIR = str(Path.home() / ".phoenix_helper" / "webengine_profile")


def _get_profile() -> QWebEngineProfile:
    profile = QWebEngineProfile("phoenix_profile")
    profile.setPersistentStoragePath(WEBENGINE_PROFILE_DIR)
    profile.setPersistentCookiesPolicy(QWebEngineProfile.ForcePersistentCookies)
    return profile


class WebEngineLoginDialog(QDialog):
    """Embedded browser dialog for logging in to the Phoenix site."""

    def __init__(self, site_base_url: str, parent: object | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("金凤站点登录")
        self.resize(900, 650)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint)

        self.site_base_url = site_base_url.rstrip("/")
        self._logged_in = False
        self._cookie_header = ""
        self._extraction_started = False

        self._profile = _get_profile()
        self._profile.setParent(self)
        self._page = QWebEnginePage(self._profile, self)
        self._view = QWebEngineView()
        self._view.setPage(self._page)
        self._view.urlChanged.connect(self._on_url_changed)
        self._view.loadFinished.connect(self._on_load_finished)

        self._build_ui()

        login_url = f"{self.site_base_url}/login.aspx"
        self._view.load(QUrl(login_url))

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self._hint = QLabel("请在下方浏览器窗口中登录金凤网站。\n登录成功后将自动获取凭证。")
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)

        layout.addWidget(self._view, 1)

        btn_layout = QHBoxLayout()
        self._cancel_btn = QPushButton("取消")
        self._cancel_btn.clicked.connect(self.reject)

        btn_layout.addStretch(1)
        btn_layout.addWidget(self._cancel_btn)
        layout.addLayout(btn_layout)

    @property
    def cookie_header(self) -> str:
        return self._cookie_header

    def _on_url_changed(self, url: QUrl) -> None:
        """Detect login success by URL change."""
        url_str = url.toString().lower()

        # Still on login page or error page
        if "login" in url_str or "error" in url_str:
            return

        # Already processing
        if self._logged_in:
            return

        # Login detected
        self._logged_in = True
        LOGGER.info("Login detected, URL: %s", url.toString())

        # Wait a bit for page to fully load before extracting cookies
        QTimer.singleShot(1000, self._start_cookie_extraction)

    def _on_load_finished(self, ok: bool) -> None:
        """Handle page load finished."""
        if not ok:
            return

        url = self._view.url().toString().lower()
        LOGGER.info("Page loaded: %s", url)

        # If we're on a non-login page and haven't started extraction
        if "login" not in url and "error" not in url and self._logged_in and not self._extraction_started:
            self._start_cookie_extraction()

    def _start_cookie_extraction(self) -> None:
        """Start extracting cookies after login detected."""
        if self._extraction_started:
            return

        self._extraction_started = True
        self._set_busy("登录成功，正在获取凭证...")
        self._cancel_btn.setEnabled(False)

        LOGGER.info("Starting cookie extraction...")

        # Try JS cookies first
        self._view.page().runJavaScript("document.cookie", 5000, self._on_js_cookies)

    def _on_js_cookies(self, js_cookies: str) -> None:
        """Handle cookies from document.cookie."""
        LOGGER.info("JS cookies result: %r", js_cookies)

        if js_cookies and js_cookies.strip():
            self._cookie_header = js_cookies.strip()
            LOGGER.info("Got cookies from document.cookie: %d chars", len(self._cookie_header))
            self._finish_success()
            return

        LOGGER.info("document.cookie empty, trying cookie store...")
        # Fallback: try cookie store for HttpOnly cookies
        self._extract_from_cookie_store()

    def _extract_from_cookie_store(self) -> None:
        """Extract cookies from the cookie store."""
        cookie_store: QWebEngineCookieStore = self._profile.cookieStore()
        self._collected_cookies: dict[str, str] = {}
        self._cookie_loop = QEventLoop()

        cookie_store.cookieAdded.connect(self._on_cookie_added)
        cookie_store.loadAllCookies()

        # Wait for cookies with timeout
        QTimer.singleShot(2000, self._cookie_loop.quit)
        self._cookie_loop.exec()

        cookie_store.cookieAdded.disconnect(self._on_cookie_added)

        if self._collected_cookies:
            self._cookie_header = "; ".join(
                f"{name}={value}" for name, value in self._collected_cookies.items()
            )
            LOGGER.info("Got cookies from cookie store: %d chars", len(self._cookie_header))
            self._finish_success()
            return

        # Failed to get cookies
        LOGGER.warning("No cookies found in cookie store")
        self._set_error("未能提取到有效的登录 Cookie，请确认已成功登录后重试。")
        self._cancel_btn.setEnabled(True)
        self._extraction_started = False

    def _on_cookie_added(self, cookie) -> None:
        """Handle cookie added from cookie store."""
        domain = cookie.domain()
        if "phoenix" not in domain and "stu.edu.cn" not in domain:
            return

        name_bytes = cookie.name()
        value_bytes = cookie.value()
        name = name_bytes.data().decode("utf-8", errors="replace")
        value = value_bytes.data().decode("utf-8", errors="replace")
        self._collected_cookies[name] = value
        LOGGER.debug("Cookie added: %s=%s", name, value[:20] if value else "")

    def _finish_success(self) -> None:
        """Finish with success and close dialog."""
        self._set_busy("凭证获取成功，正在关闭...")
        LOGGER.info("Cookie extraction successful, closing dialog")
        # Use QTimer to allow UI to update before closing
        QTimer.singleShot(500, self.accept)

    def _set_busy(self, message: str) -> None:
        """Show busy state."""
        self._hint.setText(message)
        self._hint.setStyleSheet("color: #1565C0; font-weight: bold;")

    def _set_error(self, message: str) -> None:
        """Show error state."""
        self._hint.setText(message)
        self._hint.setStyleSheet("color: #E65100; font-weight: bold;")
