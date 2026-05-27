from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class QrDisplayWidget(QWidget):
    """Display QR code for mobile scanning, along with IP and status info."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        qr_layout = QVBoxLayout()
        self.qr_label = QLabel()
        self.qr_label.setFixedSize(220, 220)
        self.qr_label.setAlignment(Qt.AlignCenter)
        self.qr_label.setStyleSheet("background: white; border: 1px solid #ddd;")
        qr_layout.addWidget(self.qr_label, alignment=Qt.AlignCenter)

        self.refresh_btn = QPushButton("刷新二维码")
        qr_layout.addWidget(self.refresh_btn, alignment=Qt.AlignCenter)
        layout.addLayout(qr_layout)

        info_layout = QVBoxLayout()
        self.ip_label = QLabel("本机地址：\n获取中...")
        self.ip_label.setStyleSheet("font-size: 13px; color: #333;")
        self.ip_label.setWordWrap(True)
        self.port_label = QLabel("监听端口：")
        self.status_label = QLabel("状态：已停止")
        self.status_label.setStyleSheet("color: #E65100; font-weight: bold;")
        self.peer_label = QLabel("已连接设备：无")

        info_layout.addWidget(self.ip_label)
        info_layout.addWidget(self.port_label)
        info_layout.addWidget(self.status_label)
        info_layout.addWidget(self.peer_label)
        info_layout.addStretch(1)
        layout.addLayout(info_layout, 1)

    def set_qr_image(self, image_bytes: bytes) -> None:
        pixmap = QPixmap()
        pixmap.loadFromData(image_bytes, "PNG")
        self.qr_label.setPixmap(pixmap.scaled(210, 210, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def clear_qr(self) -> None:
        self.qr_label.clear()
        self.ip_label.setText("本机地址：\n-")
        self.port_label.setText("监听端口：-")
        self.status_label.setText("状态：已停止")
        self.status_label.setStyleSheet("color: #E65100; font-weight: bold;")
        self.peer_label.setText("已连接设备：无")

    def set_info(self, ips: list[str], port: int) -> None:
        self.ip_label.setText("本机地址：\n" + "\n".join(ips))
        self.port_label.setText(f"监听端口：{port}")
        self.status_label.setText("状态：运行中")
        self.status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
