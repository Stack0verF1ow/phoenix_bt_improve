from __future__ import annotations

import json
import logging
import socket
import threading
import time
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from PySide6.QtCore import QThread, Signal, QObject
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from phoenix_helper.config import AppConfig
from phoenix_helper.lan.server import LanServer
from phoenix_helper.lan.qr_generator import generate_qr_image, qr_image_to_bytes
from phoenix_helper.lan.ip_utils import get_lan_ips
from phoenix_helper.ui.qr_display_widget import QrDisplayWidget
from phoenix_helper.ui.widgets import LogBox

LOGGER = logging.getLogger(__name__)


class SeedWorker(QThread):
    """Run the auto-seed flow in a background thread to avoid blocking the HTTP server."""

    log = Signal(str)
    status_changed = Signal(str, str)  # upload_id, status_text
    finished_ok = Signal(str, str)  # upload_id, detail_url
    failed = Signal(str, str)  # upload_id, error_message

    def __init__(self, config: AppConfig, upload_id: str, title: str,
                 category: str, description: str, tags: list[str]) -> None:
        super().__init__()
        self.config = config
        self.upload_id = upload_id
        self.title = title
        self.category = category
        self.description = description
        self.tags = tags

    def run(self) -> None:
        from phoenix_helper.lan.file_store import FileStore
        from phoenix_helper.models import ResourceDraft
        from phoenix_helper.torrent.creator import create_torrent, recommended_piece_length
        from phoenix_helper.phoenix.client import PhoenixClient
        from phoenix_helper.clients.utorrent import UTorrentClient, UTorrentConfig

        store = FileStore(self.config.upload_receive_dir)
        meta = store.get_meta(self.upload_id)
        if not meta:
            self.failed.emit(self.upload_id, "找不到上传记录")
            return

        source_path = Path(meta["file_path"])
        if not source_path.exists():
            self.failed.emit(self.upload_id, f"找不到文件：{source_path}")
            return

        self.log.emit(f"[{meta['original_name']}] 开始制种...")
        self.status_changed.emit(self.upload_id, "制种中")

        draft = ResourceDraft.from_path(source_path)
        draft.title = self.title or draft.title
        draft.category = self.category or "0"
        draft.description = self.description or draft.description
        draft.tags = self.tags or []

        self.config.ensure_directories()
        self.config.generated_torrent_dir.mkdir(parents=True, exist_ok=True)
        torrent_path = self.config.generated_torrent_dir / f"{source_path.stem}.torrent"
        piece_length = recommended_piece_length(draft.total_size)
        create_torrent(source_path, self.config.tracker_url, torrent_path,
                       piece_length=piece_length)

        self.log.emit(f"[{meta['original_name']}] 上传到金凤站点...")
        self.status_changed.emit(self.upload_id, "上传站点中")

        client = PhoenixClient(self.config)
        result = client.upload_torrent(draft, torrent_path)
        if not result.success:
            msg = f"上传失败：{result.message}"
            self.log.emit(f"[{meta['original_name']}] {msg}")
            self.failed.emit(self.upload_id, msg)
            return

        self.log.emit(f"[{meta['original_name']}] 下载官方种子...")
        self.status_changed.emit(self.upload_id, "下载种子中")

        final_torrent_path = client.download_final_torrent(
            result.torrent_url, draft.title, self.config.final_torrent_dir
        )

        from phoenix_helper.clients.utorrent import UTorrentClient, UTorrentConfig
        utorrent = UTorrentClient(UTorrentConfig(
            executable=self.config.utorrent_executable,
        ))
        utorrent.open_torrent(final_torrent_path, save_path=source_path.parent)

        store.update_meta(
            self.upload_id,
            auto_seed=True,
            seed_status="done",
            seed_detail_url=result.detail_url,
            seed_torrent_url=result.torrent_url,
            title=draft.title,
        )

        self.log.emit(f"[{meta['original_name']}] 做种完成！")
        self.status_changed.emit(self.upload_id, "做种完成")
        self.finished_ok.emit(self.upload_id, result.detail_url)


class LanTabSignals(QObject):
    log = Signal(str)
    file_received = Signal(str, str)
    device_connected = Signal(str, str)  # ip, name
    devices_updated = Signal(list)  # list of device dicts


class LanTab(QWidget):
    """Third tab: LAN file transfer controls."""

    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self.server = LanServer(config)
        self.signals = LanTabSignals()
        self._seed_workers: list[SeedWorker] = []
        self._poll_stop = threading.Event()
        self._build_ui()

        self.server.on_seed_ready = self._on_seed_requested
        self.server.on_file_received = self._on_file_received
        self.server.on_device_connected = self._on_device_connected

        self.signals.log.connect(self._append_log)
        self.signals.file_received.connect(self._on_file_received_ui)
        self.signals.device_connected.connect(self._add_device_row)
        self.signals.devices_updated.connect(self._update_device_table)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self.qr_widget = QrDisplayWidget()
        self.qr_widget.refresh_btn.clicked.connect(self._refresh_qr)
        layout.addWidget(self.qr_widget)

        ctrl_layout = QHBoxLayout()
        self.start_btn = QPushButton("启动服务")
        self.start_btn.setStyleSheet(
            "QPushButton { font-size: 14px; padding: 6px 20px; }"
        )
        self.start_btn.clicked.connect(self._toggle_server)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(self.config.lan_port)

        ctrl_layout.addWidget(QLabel("端口："))
        ctrl_layout.addWidget(self.port_spin)
        ctrl_layout.addStretch(1)
        ctrl_layout.addWidget(self.start_btn)
        layout.addLayout(ctrl_layout)

        # Connected devices section
        device_group = QGroupBox("已连接设备")
        device_layout = QVBoxLayout(device_group)
        self.device_table = QTableWidget(0, 3)
        self.device_table.setHorizontalHeaderLabels(["设备名称", "IP 地址", "连接时间"])
        self.device_table.horizontalHeader().setStretchLastSection(True)
        self.device_table.setColumnWidth(0, 160)
        self.device_table.setColumnWidth(1, 140)
        self.device_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.device_table.setMaximumHeight(120)
        device_layout.addWidget(self.device_table)
        layout.addWidget(device_group)

        log_group = QGroupBox("传输记录")
        log_layout = QVBoxLayout(log_group)
        self.transfer_log = LogBox()
        self.transfer_log.setMaximumHeight(200)
        log_layout.addWidget(self.transfer_log)
        layout.addWidget(log_group)

        layout.addStretch(1)

    def _toggle_server(self) -> None:
        if self.server.is_running:
            self._poll_stop.set()
            self.server.stop()
            self.start_btn.setText("启动服务")
            self.qr_widget.clear_qr()
            self.device_table.setRowCount(0)
            self._append_log("LAN 传输服务已停止")
        else:
            port = self.port_spin.value()
            try:
                actual_port = self.server.start(port)
                self.config.lan_port = actual_port
                self.start_btn.setText("停止服务")
                self._refresh_qr()
                self._poll_stop.clear()
                threading.Thread(target=self._poll_devices, daemon=True).start()
                self._append_log(f"LAN 传输服务已启动，端口：{actual_port}")
            except Exception as exc:
                self._append_log(f"启动失败：{exc}")
                LOGGER.exception("Failed to start LAN server")

    def _refresh_qr(self) -> None:
        if not self.server.is_running:
            return
        qr_content = self.server.get_qr_content()
        image = generate_qr_image(qr_content)
        image_bytes = qr_image_to_bytes(image)
        self.qr_widget.set_qr_image(image_bytes)
        ips = get_lan_ips()
        self.qr_widget.set_info(ips or ["无法检测到 LAN IP"], self.server.listen_port)

    def _poll_devices(self) -> None:
        """Poll GET /api/devices every 3 seconds to keep device list up-to-date."""
        while not self._poll_stop.is_set():
            try:
                if self.server.is_running:
                    port = self.server.listen_port
                    url = f"http://127.0.0.1:{port}/api/devices"
                    resp = urlopen(url, timeout=2)
                    data = json.loads(resp.read().decode())
                    devices = data.get("devices", [])
                    self.signals.devices_updated.emit(devices)
            except Exception:
                pass
            self._poll_stop.wait(3)

    def _update_device_table(self, devices: list[dict]) -> None:
        self.device_table.setRowCount(len(devices))
        for i, d in enumerate(devices):
            self.device_table.setItem(i, 0, QTableWidgetItem(d.get("name", "")))
            self.device_table.setItem(i, 1, QTableWidgetItem(d.get("ip", "")))
            t = time.strftime("%H:%M:%S", time.localtime(time.time()))
            self.device_table.setItem(i, 2, QTableWidgetItem(t))

    def _on_device_connected(self, ip: str, name: str) -> None:
        """Called from server thread when a device registers."""
        self.signals.device_connected.emit(ip, name)

    def _add_device_row(self, ip: str, name: str) -> None:
        self._append_log(f"设备已连接：{name or ip}")

    def _on_seed_requested(self, upload_id: str, title: str, category: str,
                           description: str, tags: list[str]) -> None:
        """Called from HTTP server thread when auto-seed is requested."""
        worker = SeedWorker(self.config, upload_id, title, category, description, tags)
        worker.log.connect(self._append_log)
        worker.finished_ok.connect(self._on_seed_done)
        worker.failed.connect(self._on_seed_failed)
        worker.finished.connect(lambda: self._seed_workers.remove(worker))
        self._seed_workers.append(worker)
        worker.start()

    def _on_seed_done(self, upload_id: str, detail_url: str) -> None:
        self._append_log(f"自动做种完成 (ID: {upload_id}) — {detail_url}")

    def _on_seed_failed(self, upload_id: str, error: str) -> None:
        self._append_log(f"自动做种失败 (ID: {upload_id}): {error}")

    def _on_file_received(self, upload_id: str, filename: str) -> None:
        """Called from HTTP server thread."""
        self.signals.file_received.emit(upload_id, filename)

    def _on_file_received_ui(self, upload_id: str, filename: str) -> None:
        self._append_log(f"收到文件：{filename}")
        meta = self.server.file_store.get_meta(upload_id)
        if meta:
            size_str = self._format_size(meta["size"])
            self._append_log(f"  大小：{size_str}，如需自动做种请在手机端确认")

    def _append_log(self, message: str) -> None:
        self.transfer_log.append_line(message)

    @staticmethod
    def _format_size(size: int) -> str:
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"
