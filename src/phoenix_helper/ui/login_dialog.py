from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from phoenix_helper.clients.browser_cookies import read_browser_cookies
from phoenix_helper.phoenix.cookies import normalize_cookie_header

LOGGER = logging.getLogger(__name__)


class LoginDialog(QDialog):
    def __init__(self, site_base_url: str, parent: object | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("获取登录凭证")
        self.setMinimumWidth(480)
        self.site_base_url = site_base_url.rstrip("/")
        self.cookie_header = ""
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        info = QLabel(
            "本工具需要金凤网站的登录凭证才能上传种子。\n\n"
            "点击下方按钮，自动从已安装的浏览器（Edge/Chrome）读取金凤网站的登录 Cookie。"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        actions = QHBoxLayout()
        auto_btn = QPushButton("自动读取浏览器 Cookie")
        auto_btn.clicked.connect(self._auto_read)
        paste_btn = QPushButton("手动粘贴 Cookie")
        paste_btn.clicked.connect(self._paste_cookie)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.reject)

        actions.addWidget(auto_btn)
        actions.addWidget(paste_btn)
        actions.addStretch(1)
        actions.addWidget(close_btn)
        layout.addLayout(actions)

    def _auto_read(self) -> None:
        self.status_label.setText("正在读取浏览器 Cookie...")
        self.status_label.setStyleSheet("color: #1976D2;")
        self.repaint()

        cookie = read_browser_cookies()
        if cookie:
            self.cookie_header = cookie
            self.status_label.setText("Cookie 读取成功！")
            self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            self.accept()
        else:
            self.status_label.setText(
                "未找到金凤网站的 Cookie。\n"
                "请先在浏览器中登录金凤网站，然后再试。"
            )
            self.status_label.setStyleSheet("color: #E65100;")

    def _paste_cookie(self) -> None:
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getMultiLineText(
            self,
            "粘贴 Cookie",
            "请从浏览器开发者工具复制 phoenix.stu.edu.cn 的 Cookie：",
            "",
        )
        if ok and text.strip():
            cookie = normalize_cookie_header(text.strip())
            if cookie:
                self.cookie_header = cookie
                self.accept()
