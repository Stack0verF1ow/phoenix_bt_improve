from __future__ import annotations

import http.client
import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from phoenix_helper.config import AppConfig
from phoenix_helper.lan.ip_utils import get_lan_ips
from phoenix_helper.lan.qr_generator import generate_qr_image, qr_image_to_bytes
from phoenix_helper.lan.server import LanServer
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
    upload_progress = Signal(str, int, int, int, int)  # name, received, total, files_done, files_total
    file_downloaded = Signal(str, int, str)  # filename, size, ip
    download_progress = Signal(str, int, int, str)  # filename, sent, total, ip


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
        self.server.on_upload_progress = self._on_upload_progress
        self.server.on_file_downloaded = self._on_file_downloaded
        self.server.on_download_progress = self._on_download_progress

        self.signals.log.connect(self._append_log)
        self.signals.file_received.connect(self._on_file_received_ui)
        self.signals.device_connected.connect(self._add_device_row)
        self.signals.devices_updated.connect(self._update_device_table)
        self.signals.upload_progress.connect(self._on_upload_progress_ui)
        self.signals.file_downloaded.connect(self._on_file_downloaded_ui)
        self.signals.download_progress.connect(self._on_download_progress_ui)

        self.setAcceptDrops(True)

    def _build_ui(self) -> None:
        main_layout = QHBoxLayout(self)

        # Left column: QR + controls + devices
        left_col = QVBoxLayout()
        self.qr_widget = QrDisplayWidget()
        self.qr_widget.refresh_btn.clicked.connect(self._refresh_qr)
        left_col.addWidget(self.qr_widget)

        ctrl_layout = QHBoxLayout()
        self.start_btn = QPushButton("启动服务")
        self.start_btn.setObjectName("startBtn")
        self.start_btn.setProperty("stopped", True)
        self.start_btn.clicked.connect(self._toggle_server)
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setFixedWidth(110)
        self.port_spin.setAlignment(Qt.AlignCenter)
        self.port_spin.setValue(self.config.lan_port)
        ctrl_layout.addWidget(QLabel("端口："))
        ctrl_layout.addWidget(self.port_spin)
        ctrl_layout.addStretch(1)
        ctrl_layout.addWidget(self.start_btn)
        left_col.addLayout(ctrl_layout)

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
        left_col.addWidget(device_group)
        main_layout.addLayout(left_col)

        # Right column: shared files + log
        right_col = QVBoxLayout()

        share_group = QGroupBox("共享文件（手机端可下载）")
        share_layout = QVBoxLayout(share_group)

        share_btn_layout = QHBoxLayout()
        self.pick_files_btn = QPushButton("选择文件")
        self.pick_files_btn.setStyleSheet(
            "QPushButton { font-size: 13px; padding: 6px 16px; color: #1976D2; border: 1px solid #1976D2; border-radius: 3px; background: white; }"
            "QPushButton:hover { background: #E3F2FD; }"
        )
        self.pick_files_btn.clicked.connect(self._pick_files)
        self.pick_folder_btn = QPushButton("选择文件夹")
        self.pick_folder_btn.setStyleSheet(
            "QPushButton { font-size: 13px; padding: 6px 16px; color: #1976D2; border: 1px solid #1976D2; border-radius: 3px; background: white; }"
            "QPushButton:hover { background: #E3F2FD; }"
        )
        self.pick_folder_btn.clicked.connect(self._pick_folder)
        self.clear_files_btn = QPushButton("清空")
        self.delete_selected_btn = QPushButton("删除选中")
        self.delete_selected_btn.clicked.connect(self._delete_selected_files)
        share_btn_layout.addWidget(self.pick_files_btn)
        share_btn_layout.addWidget(self.pick_folder_btn)
        share_btn_layout.addStretch(1)
        share_btn_layout.addWidget(self.clear_files_btn)
        share_btn_layout.addWidget(self.delete_selected_btn)
        share_layout.addLayout(share_btn_layout)

        # Drop hint area
        self._share_drop_hint = QLabel("拖放文件或文件夹到此处")
        self._share_drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._share_drop_hint.setMinimumHeight(80)
        self._share_drop_hint.setStyleSheet(
            "QLabel {"
            "  border: 2px dashed #ccc;"
            "  border-radius: 6px;"
            "  padding: 14px;"
            "  color: #999;"
            "  font-size: 13px;"
            "}"
            "QLabel:hover { border-color: #1976D2; color: #1976D2; }"
        )
        share_layout.addWidget(self._share_drop_hint)

        self.shared_files_list = QListWidget()
        self.shared_files_list.setSelectionMode(
            QListWidget.SelectionMode.ExtendedSelection)
        share_layout.addWidget(self.shared_files_list)

        self.file_count_label = QLabel("未选择任何文件")
        self.file_count_label.setStyleSheet("color: #999; font-size: 12px; padding: 2px;")
        share_layout.addWidget(self.file_count_label)
        right_col.addWidget(share_group)

        log_group = QGroupBox("传输记录")
        log_layout = QVBoxLayout(log_group)
        self.transfer_log = LogBox()
        log_layout.addWidget(self.transfer_log)
        right_col.addWidget(log_group)
        main_layout.addLayout(right_col)

    def _pick_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "选择要共享的文件")
        if not paths:
            return
        from pathlib import Path
        self.server.add_shared_files([Path(p) for p in paths])
        self._refresh_shared_files_list()
        self._append_log(f"已添加 {len(paths)} 个文件到共享列表")

    def _pick_folder(self) -> None:
        paths = QFileDialog.getExistingDirectory(self, "选择要共享的文件夹")
        if not paths:
            return
        from pathlib import Path
        folder = Path(paths)
        if not folder.is_dir():
            return
        files = [f for f in folder.iterdir() if f.is_file()]
        self.server.add_shared_files(files)
        self._refresh_shared_files_list()
        self._append_log(f"已添加 {len(files)} 个文件从 {folder.name}")

    def _clear_shared_files(self) -> None:
        count = len(self.server.shared_files)
        self.server.clear_shared_files()
        self._refresh_shared_files_list()
        if count:
            self._append_log(f"已清空共享列表（{count} 个文件）")

    def _refresh_shared_files_list(self) -> None:
        self.shared_files_list.clear()
        for fp in self.server.shared_files:
            size_str = self._format_size(fp.stat().st_size) if fp.exists() else "?"
            self.shared_files_list.addItem(QListWidgetItem(f"{fp.name}  ({size_str})"))
        count = len(self.server.shared_files)
        self.file_count_label.setText(f"已选 {count} 个文件" if count else "未选择任何文件")

    def _toggle_server(self) -> None:
        if self.server.is_running:
            self._poll_stop.set()
            self.server.stop()
            self.start_btn.setText("启动服务")
            self.start_btn.setProperty("stopped", True)
            self.start_btn.style().unpolish(self.start_btn)
            self.start_btn.style().polish(self.start_btn)
            self.qr_widget.clear_qr()
            self.device_table.setRowCount(0)
            self._append_log("LAN 传输服务已停止")
        else:
            port = self.port_spin.value()
            try:
                actual_port = self.server.start(port)
                self.config.lan_port = actual_port
                self.start_btn.setText("停止服务")
                self.start_btn.setProperty("stopped", False)
                self.start_btn.style().unpolish(self.start_btn)
                self.start_btn.style().polish(self.start_btn)
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
                    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
                    conn.request("GET", "/api/devices")
                    resp = conn.getresponse()
                    data = json.loads(resp.read().decode())
                    devices = data.get("devices", [])
                    self.signals.devices_updated.emit(devices)
                    conn.close()
            except Exception:
                pass
            self._poll_stop.wait(3)

    def _update_device_table(self, devices: list[dict]) -> None:
        self.device_table.setRowCount(len(devices))
        names = []
        for i, d in enumerate(devices):
            name = d.get("name", "")
            names.append(name)
            self.device_table.setItem(i, 0, QTableWidgetItem(name))
            self.device_table.setItem(i, 1, QTableWidgetItem(d.get("ip", "")))
            ts = d.get("connected_at", 0)
            if ts:
                t = time.strftime("%H:%M:%S", time.localtime(ts))
            else:
                t = time.strftime("%H:%M:%S", time.localtime(time.time()))
            self.device_table.setItem(i, 2, QTableWidgetItem(t))
        self.qr_widget.set_peer_count(len(devices), names)

    def _on_device_connected(self, ip: str, name: str) -> None:
        """Called from server thread when a device registers."""
        self.signals.device_connected.emit(ip, name)

    def _on_upload_progress(self, filename: str, received: int, total: int,
                            files_done: int, files_total: int) -> None:
        """Called from server thread during chunked read."""
        self.signals.upload_progress.emit(filename, received, total, files_done, files_total)

    def _on_upload_progress_ui(self, filename: str, received: int, total: int,
                                files_done: int, files_total: int) -> None:
        pct = int(received * 100 / total) if total > 0 else 0
        recv_str = self._format_size(received)
        total_str = self._format_size(total)
        self.transfer_log.update_progress(
            f"接收中：{filename} {recv_str}/{total_str} ({pct}%) [{files_done}/{files_total}]"
        )

    def _add_device_row(self, ip: str, name: str) -> None:
        self._append_log(f"设备已连接：{name or ip}")

    def _on_file_downloaded(self, filename: str, size: int, ip: str) -> None:
        """Called from server thread when a file is downloaded."""
        self.signals.file_downloaded.emit(filename, size, ip)

    def _on_file_downloaded_ui(self, filename: str, size: int, ip: str) -> None:
        size_str = self._format_size(size)
        self._append_log(f"设备 {ip} 下载了：{filename}（{size_str}）")

    def _on_download_progress(self, filename: str, sent: int, total: int, ip: str) -> None:
        """Called from server thread during download."""
        self.signals.download_progress.emit(filename, sent, total, ip)

    def _on_download_progress_ui(self, filename: str, sent: int, total: int, ip: str) -> None:
        pct = int(sent * 100 / total) if total > 0 else 0
        sent_str = self._format_size(sent)
        total_str = self._format_size(total)
        self.transfer_log.update_progress(
            f"发送中：{filename} {sent_str}/{total_str} ({pct}%) → {ip}"
        )

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
            file_path = meta.get("file_path", "")
            if file_path:
                folder = os.path.dirname(file_path)
                try:
                    if os.name == "nt":
                        os.startfile(folder)
                    else:
                        subprocess.Popen(["xdg-open", folder])
                except Exception as exc:
                    LOGGER.warning("Failed to open folder %s: %s", folder, exc)

    def _delete_selected_files(self) -> None:
        """Remove selected files from the shared list."""
        selected = self.shared_files_list.selectedItems()
        if not selected:
            return
        count = 0
        for item in selected:
            row = self.shared_files_list.row(item)
            self.shared_files_list.takeItem(row)
            # The actual file removal relies on server's shared_files list
            # We need to find the matching path
            text = item.text()
            name = text.rsplit("  (", 1)[0] if "  (" in text else text
            for fp in list(self.server.shared_files):
                if fp.name == name:
                    self.server.remove_shared_file(fp)
                    count += 1
        self._refresh_shared_files_list()
        if count:
            self._append_log(f"已删除 {count} 个文件")

    def _append_log(self, message: str) -> None:
        self.transfer_log.append_line(message)

    @staticmethod
    def _format_size(size: int) -> str:
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"

    # ── Drag & Drop ──────────────────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._share_drop_hint.setStyleSheet(
                "QLabel {"
                "  border: 2px dashed #4CAF50;"
                "  border-radius: 6px;"
                "  padding: 14px;"
                "  color: #4CAF50;"
                "  font-size: 13px;"
                "  background-color: #E8F5E9;"
                "}"
            )
            self._share_drop_hint.setText("松开鼠标即可添加文件")

    def dragLeaveEvent(self, event) -> None:
        self._reset_drop_hint()

    def dropEvent(self, event: QDropEvent) -> None:
        self._reset_drop_hint()
        urls = event.mimeData().urls()
        if not urls:
            return
        paths = []
        for url in urls:
            p = Path(url.toLocalFile())
            if p.exists():
                if p.is_dir():
                    paths.extend(f for f in p.iterdir() if f.is_file())
                else:
                    paths.append(p)
        if paths:
            self.server.add_shared_files(paths)
            self._refresh_shared_files_list()
            self._append_log(f"拖拽添加了 {len(paths)} 个文件")
            event.acceptProposedAction()

    def _reset_drop_hint(self) -> None:
        self._share_drop_hint.setText("拖放文件或文件夹到此处")
        self._share_drop_hint.setStyleSheet(
            "QLabel {"
            "  border: 2px dashed #ccc;"
            "  border-radius: 6px;"
            "  padding: 14px;"
            "  color: #999;"
            "  font-size: 13px;"
            "}"
            "QLabel:hover { border-color: #1976D2; color: #1976D2; }"
        )
