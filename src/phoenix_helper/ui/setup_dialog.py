from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from phoenix_helper.clients.discovery import find_utorrent_executable
from phoenix_helper.clients.utorrent import UTorrentClient, UTorrentConfig
from phoenix_helper.config import AppConfig

LOGGER = logging.getLogger(__name__)


class SetupDialog(QDialog):
    def __init__(self, config: AppConfig, parent: object | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("金凤本地做种助手 - 首次配置")
        self.setMinimumWidth(500)
        self._build_ui()
        self._auto_detect()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Welcome message
        welcome = QLabel(
            "欢迎使用金凤本地做种助手！\n\n"
            "本工具需要 µTorrent 客户端配合使用。请确保 µTorrent 已安装并启用 WebUI 功能。"
        )
        welcome.setWordWrap(True)
        layout.addWidget(welcome)

        # µTorrent detection group
        utorrent_group = QGroupBox("µTorrent 配置")
        utorrent_layout = QFormLayout(utorrent_group)

        self.utorrent_path_label = QLabel("未检测到")
        self.utorrent_path_label.setWordWrap(True)
        detect_btn = QPushButton("自动检测")
        detect_btn.clicked.connect(self._auto_detect)
        path_layout = QHBoxLayout()
        path_layout.addWidget(self.utorrent_path_label, 1)
        path_layout.addWidget(detect_btn)
        utorrent_layout.addRow("µTorrent 路径:", path_layout)

        layout.addWidget(utorrent_group)

        # WebUI configuration group
        webui_group = QGroupBox("WebUI 配置")
        webui_layout = QFormLayout(webui_group)

        self.webui_url_input = QLineEdit(self.config.utorrent_webui_url or "http://127.0.0.1:8080/gui/")
        self.webui_user_input = QLineEdit(self.config.utorrent_webui_username)
        self.webui_password_input = QLineEdit(self.config.utorrent_webui_password)
        self.webui_password_input.setEchoMode(QLineEdit.Password)

        webui_layout.addRow("WebUI 地址:", self.webui_url_input)
        webui_layout.addRow("用户名:", self.webui_user_input)
        webui_layout.addRow("密码:", self.webui_password_input)

        test_btn = QPushButton("测试连接")
        test_btn.clicked.connect(self._test_webui)
        webui_layout.addRow("", test_btn)

        layout.addWidget(webui_group)

        # Instructions group
        instructions_group = QGroupBox("如何启用 WebUI")
        instructions_layout = QVBoxLayout(instructions_group)
        instructions = QTextEdit()
        instructions.setReadOnly(True)
        instructions.setMaximumHeight(150)
        instructions.setPlainText(
            "如果 WebUI 未启用，请按以下步骤操作：\n"
            "1. 打开 µTorrent\n"
            "2. 点击菜单「选项」→「设置」\n"
            "3. 选择左侧的「Web UI」\n"
            "4. 勾选「启用 Web UI」\n"
            "5. 设置端口号（建议 5669 或 8080）\n"
            "6. 可选：设置用户名和密码\n"
            "7. 点击「确定」保存"
        )
        instructions_layout.addWidget(instructions)
        layout.addWidget(instructions_group)

        # Buttons
        button_layout = QHBoxLayout()
        self.status_label = QLabel("")
        button_layout.addWidget(self.status_label, 1)

        skip_btn = QPushButton("跳过")
        skip_btn.clicked.connect(self.reject)
        save_btn = QPushButton("保存配置")
        save_btn.clicked.connect(self._save_config)
        button_layout.addWidget(skip_btn)
        button_layout.addWidget(save_btn)
        layout.addLayout(button_layout)

    def _auto_detect(self) -> None:
        path = find_utorrent_executable()
        if path:
            self.utorrent_path_label.setText(str(path))
            self.config.utorrent_executable = str(path)
        else:
            self.utorrent_path_label.setText("未检测到，请手动选择")

    def _test_webui(self) -> None:
        url = self.webui_url_input.text().strip()
        username = self.webui_user_input.text().strip()
        password = self.webui_password_input.text()

        if not url:
            QMessageBox.warning(self, "错误", "请输入 WebUI 地址")
            return

        client = UTorrentClient(UTorrentConfig(
            webui_url=url,
            username=username,
            password=password,
        ))

        try:
            client.check_webui()
            self.status_label.setText("✓ 连接成功")
            self.status_label.setStyleSheet("color: green;")
        except Exception as e:
            self.status_label.setText("✗ 连接失败")
            self.status_label.setStyleSheet("color: red;")
            QMessageBox.warning(
                self,
                "连接失败",
                f"无法连接到 µTorrent WebUI。\n\n"
                f"请检查：\n"
                f"1. µTorrent 是否已启动\n"
                f"2. WebUI 是否已启用\n"
                f"3. 地址和端口是否正确\n"
                f"4. 用户名和密码是否正确\n\n"
                f"错误信息: {e}"
            )

    def _save_config(self) -> None:
        self.config.utorrent_webui_url = self.webui_url_input.text().strip()
        self.config.utorrent_webui_username = self.webui_user_input.text().strip()
        self.config.utorrent_webui_password = self.webui_password_input.text()
        self.accept()
