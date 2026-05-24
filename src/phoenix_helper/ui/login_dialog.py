from __future__ import annotations

from typing import Any

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout

from phoenix_helper.phoenix.cookies import PHOENIX_HOST, cookie_header_from_cookie_items

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
except ImportError:  # pragma: no cover - depends on optional Qt component
    QWebEngineView = None  # type: ignore[assignment]


class LoginDialog(QDialog):
    def __init__(self, site_base_url: str, parent: object | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("网页登录")
        self.resize(980, 720)
        self.site_base_url = site_base_url.rstrip("/")
        self.cookie_header = ""
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        info = QLabel("请在此窗口完成学校账号登录。登录成功后点击“保存登录状态”。")
        info.setWordWrap(True)
        layout.addWidget(info)

        if QWebEngineView is None:
            layout.addWidget(QLabel("当前打包缺少 QtWebEngine，无法显示内置网页登录窗口。"))
            close_button = QPushButton("关闭")
            close_button.clicked.connect(self.reject)
            layout.addWidget(close_button)
            return

        self.web_view = QWebEngineView()
        self.web_view.setUrl(QUrl(self.site_base_url))
        layout.addWidget(self.web_view, 1)

        actions = QHBoxLayout()
        reload_button = QPushButton("刷新")
        save_button = QPushButton("保存登录状态")
        close_button = QPushButton("关闭")
        reload_button.clicked.connect(self.web_view.reload)
        save_button.clicked.connect(self.save_login_state)
        close_button.clicked.connect(self.reject)
        actions.addStretch(1)
        actions.addWidget(reload_button)
        actions.addWidget(save_button)
        actions.addWidget(close_button)
        layout.addLayout(actions)

    def save_login_state(self) -> None:
        if QWebEngineView is None:
            self.reject()
            return
        self.web_view.page().profile().cookieStore().loadAllCookies()
        self.web_view.page().runJavaScript("document.cookie", 0, self._handle_document_cookie)

    def _handle_document_cookie(self, document_cookie: Any) -> None:
        cookie_header = str(document_cookie or "").strip()
        if cookie_header:
            self.cookie_header = cookie_header
            self.accept()
            return
        self._collect_store_cookies()

    def _collect_store_cookies(self) -> None:
        store = self.web_view.page().profile().cookieStore()
        collected: list[dict[str, str]] = []

        def on_cookie_added(cookie: object) -> None:
            domain = bytes(cookie.domain()).decode("utf-8", errors="replace") if hasattr(cookie.domain(), "__bytes__") else str(cookie.domain())
            name = bytes(cookie.name()).decode("utf-8", errors="replace")
            value = bytes(cookie.value()).decode("utf-8", errors="replace")
            collected.append({"domain": domain, "name": name, "value": value})

        def finish() -> None:
            try:
                store.cookieAdded.disconnect(on_cookie_added)
            except TypeError:
                pass
            self.cookie_header = cookie_header_from_cookie_items(collected, PHOENIX_HOST)
            if self.cookie_header:
                self.accept()
            else:
                QMessageBox.warning(self, "未检测到登录状态", "没有从网页登录窗口中读取到金凤 Cookie，请确认已经登录成功。")

        store.cookieAdded.connect(on_cookie_added)
        store.loadAllCookies()
        QTimer.singleShot(500, finish)
