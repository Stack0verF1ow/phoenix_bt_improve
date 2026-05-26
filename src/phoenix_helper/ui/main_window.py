from __future__ import annotations

import logging
import webbrowser
from pathlib import Path

import requests
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QProgressBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from phoenix_helper.clients.discovery import find_utorrent_executable
from phoenix_helper.clients.utorrent import UTorrentClient, UTorrentConfig
from phoenix_helper.config import AppConfig, load_app_config, save_app_config, user_config_path
from phoenix_helper.models import ResourceDraft, format_size
from phoenix_helper.phoenix.client import PhoenixClient
from phoenix_helper.phoenix.discovery import discover_tracker_from_default_sample, discover_tracker_from_torrent
from phoenix_helper.torrent.creator import create_torrent, recommended_piece_length
from phoenix_helper.utils.paths import safe_filename, unique_path
from phoenix_helper.ui.http_login_dialog import HttpLoginDialog
from phoenix_helper.ui.setup_dialog import SetupDialog
from phoenix_helper.ui.widgets import LogBox

CATEGORIES = [
    ("0", "未分类"),
    ("1", "软件"),
    ("2", "音乐"),
    ("3", "电视"),
    ("4", "电影"),
    ("5", "图书"),
    ("6", "游戏"),
    ("7", "动漫"),
]

LOGGER = logging.getLogger(__name__)

WEBENGINE_PROFILE_DIR = str(Path.home() / ".phoenix_helper" / "webengine_profile")
QUOTA_MARKER = "cpContent__cphContent_lblCountUpload"


def _fetch_quota_via_http(upload_url: str, cookie_header: str) -> str:
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })
    for pair in cookie_header.split(";"):
        pair = pair.strip()
        if "=" not in pair:
            continue
        name, value = pair.split("=", 1)
        session.cookies.set(name.strip(), value.strip(), domain="phoenix.stu.edu.cn", path="/")
    resp = session.get(upload_url, timeout=10)
    # Check if we were redirected to login page (session expired)
    if "login.aspx" in resp.url.lower():
        LOGGER.warning("Quota fetch redirected to login page, session may have expired")
        return ""
    text = resp.text
    idx = text.find(QUOTA_MARKER)
    if idx < 0:
        return ""
    start = text.find(">", idx) + 1
    end = text.find("<", start)
    if start > 0 and end > start:
        return text[start:end].strip()
    return ""


class CreateTorrentWorker(QThread):
    """Create torrent in background thread."""
    log = Signal(str)
    finished_ok = Signal(Path)  # torrent_path
    failed = Signal(str)

    def __init__(self, config: AppConfig, draft: ResourceDraft) -> None:
        super().__init__()
        self.config = config
        self.draft = draft

    def run(self) -> None:
        try:
            self.config.ensure_directories()

            self.log.emit("正在生成种子...")
            torrent_path = unique_path(
                self.config.generated_torrent_dir / f"{safe_filename(self.draft.title)}.torrent"
            )
            piece_length = recommended_piece_length(self.draft.total_size)
            create_torrent(
                self.draft.source_path,
                self.config.tracker_url,
                torrent_path,
                piece_length=piece_length,
            )
            self.log.emit(f"种子已生成：{torrent_path}")
            self.finished_ok.emit(torrent_path)
        except Exception as exc:
            self.failed.emit(str(exc))


class UploadTorrentWorker(QThread):
    """Upload torrent to site via HTTP in background thread."""
    log = Signal(str)
    finished_ok = Signal(str, str)  # (detail_url, torrent_url)
    failed = Signal(str)

    def __init__(self, config: AppConfig, draft: ResourceDraft, torrent_path: Path) -> None:
        super().__init__()
        self.config = config
        self.draft = draft
        self.torrent_path = torrent_path

    def run(self) -> None:
        try:
            self.log.emit("正在上传种子到金凤站点...")
            client = PhoenixClient(self.config)
            result = client.upload_torrent(self.draft, self.torrent_path)

            if result.success:
                self.log.emit(f"上传成功，详情页：{result.detail_url}")
                self.finished_ok.emit(result.detail_url, result.torrent_url)
            else:
                self.failed.emit(result.message)
        except Exception as exc:
            self.failed.emit(str(exc))


class DownloadFinalTorrentWorker(QThread):
    """Download final torrent and open uTorrent in background thread."""
    log = Signal(str)
    finished_ok = Signal(str, str)  # (message, detail_url)
    failed = Signal(str)

    def __init__(self, config: AppConfig, draft: ResourceDraft, detail_url: str, torrent_url: str) -> None:
        super().__init__()
        self.config = config
        self.draft = draft
        self.detail_url = detail_url
        self.torrent_url = torrent_url

    def run(self) -> None:
        try:
            self.config.ensure_directories()

            # Download final torrent
            self.log.emit("正在下载站点种子...")
            client = PhoenixClient(self.config)
            final_torrent_path = client.download_final_torrent(
                self.torrent_url, self.draft.title, self.config.final_torrent_dir
            )
            self.log.emit(f"站点种子已下载：{final_torrent_path}")

            # Open uTorrent
            final_torrent = Path(final_torrent_path)
            save_path = self.draft.source_path.parent
            self.log.emit(f"正在打开 uTorrent，下载目录：{save_path}")
            utorrent = UTorrentClient(UTorrentConfig(
                executable=self.config.utorrent_executable,
                webui_url=self.config.utorrent_webui_url,
                username=self.config.utorrent_webui_username,
                password=self.config.utorrent_webui_password,
            ))
            utorrent.open_torrent(final_torrent, save_path=save_path)
            self.log.emit("uTorrent 已启动，等待做种...")

            self.finished_ok.emit(
                "uTorrent 已打开种子文件，下载完成后会自动做种。\n请保持 uTorrent 运行。",
                self.detail_url,
            )
        except Exception as exc:
            self.failed.emit(str(exc))


class QuotaWorker(QThread):
    """Fetch daily upload quota via HTTP."""
    result = Signal(str)
    failed = Signal(str)

    def __init__(self, upload_url: str, cookie_header: str) -> None:
        super().__init__()
        self.upload_url = upload_url
        self.cookie_header = cookie_header

    def run(self) -> None:
        try:
            quota = _fetch_quota_via_http(self.upload_url, self.cookie_header)
            if quota:
                self.result.emit(quota)
            else:
                self.failed.emit("无法获取上传次数")
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("金凤本地做种助手")
        self.resize(920, 720)
        self.setAcceptDrops(True)
        try:
            self.config = load_app_config()
        except Exception:
            LOGGER.exception("failed to load saved app config")
            self.config = AppConfig()
        self.draft: ResourceDraft | None = None
        self._create_torrent_worker: CreateTorrentWorker | None = None
        self._upload_worker: UploadTorrentWorker | None = None
        self._download_final_worker: DownloadFinalTorrentWorker | None = None
        self._quota_worker: QuotaWorker | None = None
        self._remaining_quota: int | None = None
        self._build_ui()
        self.log(f"已加载本机配置：{user_config_path()}")
        self._check_first_run()
        self._update_login_status()
        self._refresh_quota()

    def _build_ui(self) -> None:
        tabs = QTabWidget()
        tabs.addTab(self._build_main_tab(), "一键做种")
        tabs.addTab(self._build_settings_tab(), "设置")
        self.setCentralWidget(tabs)

    def _check_first_run(self) -> None:
        if not self.config.utorrent_executable:
            self.log("首次运行，打开配置向导...")
            self._show_setup_dialog()

    def _show_setup_dialog(self) -> None:
        dialog = SetupDialog(self.config, self)
        if dialog.exec() == QDialog.Accepted:
            self._sync_inputs_from_config()
            self.save_settings(silent=True)
            self.log("配置已保存。")

    def _sync_inputs_from_config(self) -> None:
        self.utorrent_exe_input.setText(self.config.utorrent_executable)

    def _build_main_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(8)

        # Quota badge + file selection in one row
        top_row = QHBoxLayout()
        self._quota_label = QLabel("今日剩余上传次数：--")
        self._quota_label.setStyleSheet(
            "QLabel {"
            "  background: #E3F2FD;"
            "  border-radius: 3px;"
            "  padding: 3px 10px;"
            "  font-size: 12px;"
            "  color: #1565C0;"
            "}"
        )
        top_row.addWidget(self._quota_label)
        top_row.addStretch(1)
        choose_file_button = QPushButton("选择文件")
        choose_folder_button = QPushButton("选择文件夹")
        choose_file_button.setStyleSheet(
            "QPushButton { font-size: 13px; padding: 6px 16px; color: #1976D2; border: 1px solid #1976D2; border-radius: 3px; background: white; }"
            "QPushButton:hover { background: #E3F2FD; }"
        )
        choose_folder_button.setStyleSheet(
            "QPushButton { font-size: 13px; padding: 6px 16px; color: #1976D2; border: 1px solid #1976D2; border-radius: 3px; background: white; }"
            "QPushButton:hover { background: #E3F2FD; }"
        )
        choose_file_button.clicked.connect(self.choose_file)
        choose_folder_button.clicked.connect(self.choose_folder)
        top_row.addWidget(choose_file_button)
        top_row.addWidget(choose_folder_button)
        layout.addLayout(top_row)

        # Drop hint
        self._drop_hint = QLabel("拖放文件或文件夹到此处")
        self._drop_hint.setAlignment(Qt.AlignCenter)
        self._drop_hint.setStyleSheet(
            "QLabel {"
            "  border: 2px dashed #ccc;"
            "  border-radius: 6px;"
            "  padding: 14px;"
            "  color: #999;"
            "  font-size: 13px;"
            "}"
        )
        self._drop_hint.setMinimumHeight(60)
        layout.addWidget(self._drop_hint)

        # Path + summary
        self.path_label = QLabel("尚未选择资源")
        self.path_label.setStyleSheet("color: #666; font-size: 12px;")
        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet("color: #999; font-size: 11px;")
        layout.addWidget(self.path_label)
        layout.addWidget(self.summary_label)

        # Form
        form_group = QGroupBox("资源信息")
        form = QFormLayout(form_group)
        form.setSpacing(6)
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("种子名称（必填）")
        self.description_input = QPlainTextEdit()
        self.description_input.setPlaceholderText("写一点种子的说明是美德（必填）")
        self.description_input.setMinimumHeight(120)
        self.category_input = QComboBox()
        for value, label in CATEGORIES:
            self.category_input.addItem(label, value)
        self.tags_input = QLineEdit()
        self.tags_input.setPlaceholderText("多个标签用空格分隔，如：动漫 高清")
        form.addRow("标题", self.title_input)
        form.addRow("简介", self.description_input)
        form.addRow("分类", self.category_input)
        form.addRow("标签", self.tags_input)
        layout.addWidget(form_group)

        # Compliance
        self.compliance_checkbox = QCheckBox("我确认上传内容符合校园网和站点规则")
        self.compliance_checkbox.setStyleSheet("font-size: 12px; color: #666;")
        layout.addWidget(self.compliance_checkbox)

        # Seed button
        action_layout = QHBoxLayout()
        self.seed_button = QPushButton("一键做种")
        self.seed_button.setStyleSheet(
            "QPushButton {"
            "  background: #1976D2;"
            "  color: white;"
            "  border: none;"
            "  border-radius: 4px;"
            "  padding: 10px 32px;"
            "  font-size: 15px;"
            "  font-weight: bold;"
            "}"
            "QPushButton:hover { background: #1565C0; }"
            "QPushButton:disabled { background: #BBDEFB; }"
            "QPushButton:pressed { background: #0D47A1; }"
        )
        self.seed_button.clicked.connect(self.start_seed)
        action_layout.addStretch(1)
        action_layout.addWidget(self.seed_button)
        action_layout.addStretch(1)
        layout.addLayout(action_layout)

        # Progress
        self.progress = QProgressBar()
        self.progress.setFixedHeight(6)
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 100)
        self.progress.setStyleSheet(
            "QProgressBar { border: none; background: #E0E0E0; border-radius: 3px; }"
            "QProgressBar::chunk { background: #1976D2; border-radius: 3px; }"
        )
        layout.addWidget(self.progress)

        # Log
        self.log_box = LogBox()
        self.log_box.setMaximumHeight(140)
        self.log_box.setStyleSheet(
            "QTextEdit {"
            "  background: #F5F5F5;"
            "  border: 1px solid #E0E0E0;"
            "  border-radius: 3px;"
            "  padding: 6px;"
            "  font-family: Consolas, monospace;"
            "  font-size: 11px;"
            "  color: #333;"
            "}"
        )
        layout.addWidget(self.log_box)
        return page

    def _build_settings_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)

        # Top action bar
        top_bar = QHBoxLayout()
        save_settings_button = QPushButton("保存设置")
        save_settings_button.setStyleSheet(
            "QPushButton { padding: 6px 20px; font-weight: bold; }"
        )
        save_settings_button.clicked.connect(lambda: self.save_settings(silent=False))
        top_bar.addWidget(save_settings_button)
        top_bar.addStretch(1)
        layout.addLayout(top_bar)

        # --- Login section ---
        login_group = QGroupBox("站点登录")
        login_form = QFormLayout(login_group)
        self._login_status_label = QLabel("未配置")
        self._login_status_label.setStyleSheet("color: #E65100; font-size: 12px;")
        self._login_btn = QPushButton("登录")
        self._login_btn.clicked.connect(self._start_login)
        clear_login_btn = QPushButton("清除")
        clear_login_btn.clicked.connect(self._clear_login)
        login_actions = QHBoxLayout()
        login_actions.addWidget(self._login_status_label, 1)
        login_actions.addWidget(self._login_btn)
        login_actions.addWidget(clear_login_btn)
        login_form.addRow("状态", login_actions)
        layout.addWidget(login_group)

        # --- Tracker section ---
        tracker_group = QGroupBox("Tracker")
        tracker_form = QFormLayout(tracker_group)
        self.tracker_input = QLineEdit(self.config.tracker_url)
        tracker_actions = QHBoxLayout()
        tracker_from_sample_button = QPushButton("从测试种子读取")
        tracker_from_file_button = QPushButton("从文件读取")
        tracker_from_sample_button.clicked.connect(self.fill_tracker_from_sample)
        tracker_from_file_button.clicked.connect(self.fill_tracker_from_file)
        tracker_actions.addWidget(self.tracker_input, 1)
        tracker_actions.addWidget(tracker_from_sample_button)
        tracker_actions.addWidget(tracker_from_file_button)
        tracker_form.addRow("地址", tracker_actions)
        layout.addWidget(tracker_group)

        # --- uTorrent section ---
        ut_group = QGroupBox("uTorrent 路径")
        ut_form = QFormLayout(ut_group)
        self.utorrent_exe_input = QLineEdit(self.config.utorrent_executable)
        ut_actions = QHBoxLayout()
        browse_utorrent_button = QPushButton("浏览")
        find_utorrent_button = QPushButton("自动查找")
        browse_utorrent_button.clicked.connect(self.browse_utorrent)
        find_utorrent_button.clicked.connect(self.fill_utorrent_path)
        ut_actions.addWidget(self.utorrent_exe_input, 1)
        ut_actions.addWidget(browse_utorrent_button)
        ut_actions.addWidget(find_utorrent_button)
        ut_form.addRow("可执行文件", ut_actions)
        layout.addWidget(ut_group)

        # Auto-save on field edit
        for line_edit in (self.tracker_input, self.utorrent_exe_input):
            line_edit.editingFinished.connect(lambda le=line_edit: self.save_settings(silent=True))

        layout.addStretch(1)
        return page

    # --- Login credential management ---

    def _update_login_status(self) -> None:
        has_login = bool(self.config.cookie_header)
        if has_login:
            self._login_status_label.setText("已配置")
            self._login_status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        else:
            self._login_status_label.setText("未配置")
            self._login_status_label.setStyleSheet("color: #E65100;")

    def _start_login(self) -> None:
        self._login_btn.setEnabled(False)
        self._login_btn.setText("登录中...")
        self._login_status_label.setText("正在打开登录窗口...")
        self._login_status_label.setStyleSheet("color: #1565C0; font-weight: bold;")
        self.log("正在打开登录窗口...")

        dialog = HttpLoginDialog(self.config, self)
        if dialog.exec() == QDialog.Accepted:
            cookie = dialog.cookie_header
            if cookie:
                self.config.cookie_header = cookie
                save_app_config(self.config)
                self._update_login_status()
                self.log("登录凭证已保存。")
                self._refresh_quota()
                self._login_btn.setEnabled(True)
                self._login_btn.setText("配置登录")
                QMessageBox.information(self, "登录成功", "登录凭证已保存，现在可以使用一键做种功能。")
            else:
                self._login_btn.setEnabled(True)
                self._login_btn.setText("配置登录")
                self._update_login_status()
                self.log("登录失败：未能提取到登录凭证。")
                QMessageBox.warning(self, "登录失败", "未能提取到有效的登录凭证，请重试。")
        else:
            self._login_btn.setEnabled(True)
            self._login_btn.setText("配置登录")
            self._update_login_status()
            self.log("登录已取消。")

    def _clear_login(self) -> None:
        self.config.cookie_header = ""
        save_app_config(self.config)
        self.log("已清除登录凭证。")
        self._update_login_status()
        self._quota_label.setText("今日剩余上传次数：请先配置登录")

    # --- Quota ---

    def _refresh_quota(self) -> None:
        if not self.config.cookie_header:
            self._quota_label.setText("今日剩余上传次数：请先配置登录")
            return
        self._quota_worker = QuotaWorker(self.config.upload_url, self.config.cookie_header)
        self._quota_worker.result.connect(self._on_quota_result)
        self._quota_worker.failed.connect(self._on_quota_failed)
        self._quota_worker.start()

    def _on_quota_result(self, count: str) -> None:
        try:
            self._remaining_quota = int(count)
        except ValueError:
            self._remaining_quota = None
        self._update_quota_label()

    def _on_quota_failed(self, msg: str) -> None:
        self.log(f"获取上传次数失败：{msg}（仅提示，不影响上传功能）")
        self._update_quota_label()

    def _update_quota_label(self) -> None:
        if self._remaining_quota is not None:
            self._quota_label.setText(f"今日剩余上传次数：{self._remaining_quota}")
        else:
            self._quota_label.setText("今日剩余上传次数：--")

    # --- Seed workflow ---

    def start_seed(self) -> None:
        if self.draft is None:
            QMessageBox.warning(self, "缺少资源", "请先选择文件或文件夹。")
            return
        if not self.tracker_input.text().strip():
            QMessageBox.warning(self, "缺少 Tracker", "请先在设置中填写金凤 Tracker 地址。")
            return
        if not self.compliance_checkbox.isChecked():
            QMessageBox.warning(self, "需要确认", "请先确认上传内容符合规则。")
            return

        if not self.config.cookie_header:
            QMessageBox.warning(
                self, "未配置登录",
                "请先在「设置」页面点击「配置登录」登录金凤站点，然后再使用一键做种功能。"
            )
            return

        self._sync_config_from_inputs()
        save_app_config(self.config)

        self.draft.title = self.title_input.text().strip()
        self.draft.description = self.description_input.toPlainText().strip()
        self.draft.category = str(self.category_input.currentData())
        self.draft.tags = [tag for tag in self.tags_input.text().split() if tag]
        self.draft.confirmed_compliance = True

        if not self.draft.title:
            QMessageBox.warning(self, "缺少标题", "请填写标题。")
            return
        if not self.draft.description:
            QMessageBox.warning(self, "缺少简介", "请填写简介。")
            return

        if self._remaining_quota is not None and self._remaining_quota <= 0:
            box = QMessageBox(self)
            box.setWindowTitle("提示")
            box.setText("今日上传次数可能已用完，继续上传可能失败。\n是否仍要尝试？")
            box.setIcon(QMessageBox.Warning)
            box.addButton("取消", QMessageBox.RejectRole)
            cont_btn = box.addButton("继续上传", QMessageBox.AcceptRole)
            box.exec()
            if box.clickedButton() != cont_btn:
                return

        self.seed_button.setEnabled(False)
        self.progress.setRange(0, 0)

        # Step 1: Create torrent in background
        self._create_torrent_worker = CreateTorrentWorker(self.config, self.draft)
        self._create_torrent_worker.log.connect(self.log)
        self._create_torrent_worker.finished_ok.connect(self._on_torrent_created)
        self._create_torrent_worker.failed.connect(self._on_seed_failed)
        self._create_torrent_worker.start()

    def _on_torrent_created(self, torrent_path: Path) -> None:
        """Torrent created, now upload via HTTP in background."""
        self.log("种子已生成，正在上传到站点...")

        # Step 2: Upload torrent via HTTP in background
        self._upload_worker = UploadTorrentWorker(self.config, self.draft, torrent_path)
        self._upload_worker.log.connect(self.log)
        self._upload_worker.finished_ok.connect(self._on_upload_complete)
        self._upload_worker.failed.connect(self._on_seed_failed)
        self._upload_worker.start()

    def _on_upload_complete(self, detail_url: str, torrent_url: str) -> None:
        """Upload complete, now download final torrent and open uTorrent."""
        if not detail_url:
            self._on_seed_failed("上传失败，未获取到详情页链接。")
            return

        if not torrent_url:
            self.log("未找到种子下载链接，请手动从详情页下载。")
            self._on_seed_success(
                "上传成功，但未找到种子下载链接。\n请手动从详情页下载种子并添加到 uTorrent。",
                detail_url,
            )
            return

        # Step 3: Download final torrent and open uTorrent
        self._download_final_worker = DownloadFinalTorrentWorker(
            self.config, self.draft, detail_url, torrent_url
        )
        self._download_final_worker.log.connect(self.log)
        self._download_final_worker.finished_ok.connect(
            lambda msg, url: self._on_seed_success(msg, url)
        )
        self._download_final_worker.failed.connect(self._on_seed_failed)
        self._download_final_worker.start()

    def _on_seed_success(self, message: str, detail_url: str) -> None:
        self.seed_button.setEnabled(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.statusBar().clearMessage()
        self.log("做种完成！")

        if self._remaining_quota is not None:
            self._remaining_quota -= 1
        self._update_quota_label()

        box = QMessageBox(self)
        box.setWindowTitle("完成")
        box.setText(message)
        box.setIcon(QMessageBox.Information)
        done_btn = box.addButton("完成", QMessageBox.AcceptRole)
        view_btn = box.addButton("查看结果", QMessageBox.ActionRole)
        box.exec()

        if box.clickedButton() == view_btn and detail_url:
            webbrowser.open(detail_url)

    def _on_seed_failed(self, message: str) -> None:
        self.seed_button.setEnabled(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.statusBar().clearMessage()
        self.log(f"失败：{message}")
        QMessageBox.critical(self, "失败", message)

    # --- Utility methods ---

    def log(self, message: str) -> None:
        self.log_box.append_line(message)

    def choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择要分享的文件")
        if path:
            self.load_draft(Path(path))

    def fill_tracker_from_sample(self) -> None:
        try:
            tracker = discover_tracker_from_default_sample()
        except Exception as exc:
            QMessageBox.warning(self, "读取 Tracker 失败", str(exc))
            return
        if not tracker:
            QMessageBox.warning(self, "读取 Tracker 失败", "没有找到测试种子或测试种子不包含 Tracker。")
            return
        self.tracker_input.setText(tracker)
        self.log("已从测试种子读取 Tracker。")
        self.save_settings(silent=True)

    def fill_tracker_from_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择已有种子", filter="Torrent (*.torrent);;All files (*)")
        if not path:
            return
        try:
            tracker = discover_tracker_from_torrent(Path(path))
        except Exception as exc:
            QMessageBox.warning(self, "读取 Tracker 失败", str(exc))
            return
        self.tracker_input.setText(tracker)
        self.log(f"已从种子读取 Tracker：{Path(path).name}")
        self.save_settings(silent=True)

    def browse_utorrent(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 µTorrent 可执行文件", filter="Executable (*.exe);;All files (*)")
        if path:
            self.utorrent_exe_input.setText(path)
            self.save_settings(silent=True)

    def fill_utorrent_path(self) -> None:
        path = find_utorrent_executable()
        if path is None:
            QMessageBox.warning(self, "未找到 µTorrent", "没有在常见安装目录找到 µTorrent，请手动浏览选择 uTorrent.exe。")
            return
        self.utorrent_exe_input.setText(str(path))
        self.log(f"已找到 µTorrent：{path}")
        self.save_settings(silent=True)

    def test_utorrent_webui(self) -> None:
        self._sync_config_from_inputs()
        client = UTorrentClient(
            UTorrentConfig(
                executable=self.config.utorrent_executable,
                webui_url=self.config.utorrent_webui_url,
                username=self.config.utorrent_webui_username,
                password=self.config.utorrent_webui_password,
            )
        )
        try:
            client.check_webui()
        except Exception as exc:
            QMessageBox.warning(
                self,
                "WebUI 检测失败",
                "无法连接 µTorrent WebUI。请在 µTorrent 选项里启用 WebUI，并确认地址、用户名和密码。\n\n"
                f"{exc}",
            )
            return
        self.save_settings(silent=True)
        self.log("µTorrent 路径已设置。")
        QMessageBox.information(self, "已保存", f"µTorrent 路径已保存。")

    def save_settings(self, silent: bool = False) -> None:
        self._sync_config_from_inputs()
        path = save_app_config(self.config)
        if not silent:
            QMessageBox.information(self, "已保存", f"设置已保存到：\n{path}")
        self.log(f"设置已保存：{path}")

    def _sync_config_from_inputs(self) -> None:
        self.config.tracker_url = self.tracker_input.text().strip()
        self.config.utorrent_executable = self.utorrent_exe_input.text().strip()

    def choose_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择要分享的文件夹")
        if path:
            self.load_draft(Path(path))

    def load_draft(self, path: Path) -> None:
        try:
            self.draft = ResourceDraft.from_path(path)
        except Exception as exc:
            QMessageBox.critical(self, "读取资源失败", str(exc))
            return
        self.path_label.setText(str(self.draft.source_path))
        self.summary_label.setText(f"文件数量：{self.draft.file_count}，总大小：{format_size(self.draft.total_size)}")
        self.title_input.setText(self.draft.title)
        self.description_input.setPlainText(self.draft.description)
        self.tags_input.setText(" ".join(self.draft.tags))
        self.log(f"已选择资源：{self.draft.source_path}")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._drop_hint.setStyleSheet(
                "QLabel {"
                "  border: 2px dashed #4CAF50;"
                "  border-radius: 8px;"
                "  padding: 20px;"
                "  color: #4CAF50;"
                "  font-size: 14px;"
                "  background-color: #E8F5E9;"
                "}"
            )
            self._drop_hint.setText("松开鼠标即可加载资源")

    def dragLeaveEvent(self, event) -> None:
        self._reset_drop_hint()

    def dropEvent(self, event: QDropEvent) -> None:
        self._reset_drop_hint()
        urls = event.mimeData().urls()
        if urls:
            path = Path(urls[0].toLocalFile())
            if path.exists():
                self.load_draft(path)
                event.acceptProposedAction()

    def _reset_drop_hint(self) -> None:
        self._drop_hint.setText("拖放文件或文件夹到此处，或点击下方按钮选择")
        self._drop_hint.setStyleSheet(
            "QLabel {"
            "  border: 2px dashed #aaa;"
            "  border-radius: 8px;"
            "  padding: 20px;"
            "  color: #888;"
            "  font-size: 14px;"
            "}"
        )
