"""Username/password login dialog using HTTP (no WebEngine needed)."""
from __future__ import annotations

import logging
from typing import cast

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from phoenix_helper.config import AppConfig
from phoenix_helper.phoenix.client import PhoenixClient

LOGGER = logging.getLogger(__name__)


class LoginWorker(QThread):
    """Run HTTP login in background thread."""
    finished_ok = Signal(str)  # cookie_header
    failed = Signal(str)

    def __init__(self, config: AppConfig, username: str, password: str) -> None:
        super().__init__()
        self.config = config
        self.username = username
        self.password = password

    def run(self) -> None:
        try:
            client = PhoenixClient(self.config)
            cookie_header = client.login(self.username, self.password)
            self.finished_ok.emit(cookie_header)
        except Exception as exc:
            self.failed.emit(str(exc))


class HttpLoginDialog(QDialog):
    """Simple login dialog with username/password fields."""

    def __init__(self, config: AppConfig, parent: object | None = None) -> None:
        super().__init__(cast(any, parent))
        self.setWindowTitle("登录金凤站点")
        self.setMinimumWidth(400)
        self.config = config
        self.cookie_header = ""
        self._worker: LoginWorker | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        info = QLabel("输入金凤站点的用户名和密码进行登录。")
        info.setWordWrap(True)
        layout.addWidget(info)

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("用户名")
        layout.addWidget(self.username_input)

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("密码")
        self.password_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.password_input)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        btn_layout = QHBoxLayout()
        self.login_btn = QPushButton("登录")
        self.login_btn.clicked.connect(self._do_login)
        self.login_btn.setDefault(True)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addStretch(1)
        btn_layout.addWidget(self.login_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _do_login(self) -> None:
        username = self.username_input.text().strip()
        password = self.password_input.text()
        if not username or not password:
            self.status_label.setText("请输入用户名和密码。")
            self.status_label.setStyleSheet("color: #E65100;")
            return

        self.login_btn.setEnabled(False)
        self.status_label.setText("正在登录...")
        self.status_label.setStyleSheet("color: #1565C0;")

        self._worker = LoginWorker(self.config, username, password)
        self._worker.finished_ok.connect(self._on_login_success)
        self._worker.failed.connect(self._on_login_failed)
        self._worker.start()

    def _on_login_success(self, cookie_header: str) -> None:
        self.cookie_header = cookie_header
        self.status_label.setText("登录成功！")
        self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        self.login_btn.setEnabled(True)
        self.accept()

    def _on_login_failed(self, error: str) -> None:
        LOGGER.warning("Login failed: %s", error)
        self.status_label.setText(f"登录失败：{error}")
        self.status_label.setStyleSheet("color: #E65100; font-weight: bold;")
        self.login_btn.setEnabled(True)
