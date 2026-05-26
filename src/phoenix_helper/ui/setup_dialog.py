"""First-run setup dialog — uTorrent path detection only."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from phoenix_helper.clients.discovery import find_utorrent_executable
from phoenix_helper.config import AppConfig

LOGGER = logging.getLogger(__name__)


class SetupDialog(QDialog):
    def __init__(self, config: AppConfig, parent: object | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("金凤本地做种助手 - 首次配置")
        self.setMinimumWidth(480)
        self._build_ui()
        self._auto_detect()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        welcome = QLabel(
            "欢迎使用金凤本地做种助手！\n\n"
            "本工具需要 uTorrent 配合使用。已自动检测到 uTorrent 路径，"
            "也可以手动浏览指定。"
        )
        welcome.setWordWrap(True)
        layout.addWidget(welcome)

        utorrent_group = QGroupBox("uTorrent 路径")
        utorrent_layout = QFormLayout(utorrent_group)
        self.utorrent_path_label = QLabel("未检测到")
        self.utorrent_path_label.setWordWrap(True)
        detect_btn = QPushButton("自动检测")
        detect_btn.clicked.connect(self._auto_detect)
        path_layout = QHBoxLayout()
        path_layout.addWidget(self.utorrent_path_label, 1)
        path_layout.addWidget(detect_btn)
        utorrent_layout.addRow("路径", path_layout)
        layout.addWidget(utorrent_group)

        info = QLabel(
            "提示：一键做种功能通过命令行直接启动 uTorrent，"
            "不需要配置 WebUI。种子上传后会自动打开 uTorrent 开始做种。"
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #666; font-size: 12px; padding: 4px 0;")
        layout.addWidget(info)

        layout.addStretch(1)

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
            self.status_label.setText("已检测到 uTorrent")
            self.status_label.setStyleSheet("color: #4CAF50;")
        else:
            self.utorrent_path_label.setText("未检测到，请手动选择")
            self.status_label.setText("未检测到 uTorrent")
            self.status_label.setStyleSheet("color: #E65100;")

    def _save_config(self) -> None:
        self.accept()
