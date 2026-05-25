from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QMimeData, QThread, Signal, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
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
from phoenix_helper.phoenix.cookies import cookie_header_from_netscape_file, normalize_cookie_header
from phoenix_helper.phoenix.discovery import discover_tracker_from_default_sample, discover_tracker_from_torrent
from phoenix_helper.torrent.creator import create_torrent, recommended_piece_length
from phoenix_helper.utils.paths import safe_filename, unique_path
from phoenix_helper.ui.login_dialog import LoginDialog
from phoenix_helper.ui.setup_dialog import SetupDialog
from phoenix_helper.ui.upload_dialog import UploadDialog
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


class CreateTorrentWorker(QThread):
    log = Signal(str)
    progress = Signal(int)
    torrent_ready = Signal(str)
    failed = Signal(str)

    def __init__(self, config: AppConfig, draft: ResourceDraft) -> None:
        super().__init__()
        self.config = config
        self.draft = draft

    def run(self) -> None:
        try:
            self.config.ensure_directories()
            torrent_path = unique_path(self.config.generated_torrent_dir / f"{safe_filename(self.draft.title)}.torrent")
            piece_length = recommended_piece_length(self.draft.total_size)
            self.log.emit(f"正在生成种子：{torrent_path}")

            def on_progress(done: int, total: int) -> None:
                percent = int(done / total * 100) if total else 100
                self.progress.emit(max(0, min(100, percent)))

            create_torrent(
                self.draft.source_path,
                self.config.tracker_url,
                torrent_path,
                piece_length=piece_length,
                progress=on_progress,
            )
            self.log.emit("种子生成完成。")
            self.torrent_ready.emit(str(torrent_path))
        except Exception as exc:
            self.failed.emit(str(exc))


class SeedWorker(QThread):
    log = Signal(str)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, config: AppConfig, draft: ResourceDraft, torrent_url: str) -> None:
        super().__init__()
        self.config = config
        self.draft = draft
        self.torrent_url = torrent_url

    def run(self) -> None:
        try:
            if self.torrent_url:
                self.log.emit("正在下载站点最终种子。")
                save_dir = self.draft.source_path.parent if self.draft.source_path.is_file() else self.draft.source_path
                final_torrent_path = PhoenixClient(self.config).download_final_torrent(
                    self.torrent_url, self.draft.title, save_dir=save_dir,
                )
            else:
                self.log.emit("未找到站点种子链接，跳过下载。")
                return

            save_path = self.draft.source_path.parent if self.draft.source_path.is_file() else self.draft.source_path

            utorrent = UTorrentClient(
                UTorrentConfig(
                    executable=self.config.utorrent_executable,
                    webui_url=self.config.utorrent_webui_url,
                    username=self.config.utorrent_webui_username,
                    password=self.config.utorrent_webui_password,
                )
            )

            # Use command line with /DIRECTORY parameter to specify download path
            self.log.emit(f"正在打开 µTorrent，下载目录：{save_path}")
            utorrent.open_torrent(final_torrent_path, save_path=save_path)
            self.log.emit("µTorrent 已启动。")

            self.finished_ok.emit("做种流程已完成。µTorrent 已打开种子文件。")
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
        self._create_worker: CreateTorrentWorker | None = None
        self._seed_worker: SeedWorker | None = None
        self._upload_dialog: UploadDialog | None = None
        self._build_ui()
        self.log(f"已加载本机配置：{user_config_path()}")
        self._check_first_run()

    def _build_ui(self) -> None:
        tabs = QTabWidget()
        tabs.addTab(self._build_main_tab(), "一键做种")
        tabs.addTab(self._build_settings_tab(), "设置")
        self.setCentralWidget(tabs)

    def _check_first_run(self) -> None:
        """Show setup dialog if WebUI is not configured."""
        if not self.config.utorrent_webui_url:
            self.log("首次运行，打开配置向导...")
            self._show_setup_dialog()

    def _show_setup_dialog(self) -> None:
        dialog = SetupDialog(self.config, self)
        if dialog.exec() == QDialog.Accepted:
            self._sync_inputs_from_config()
            self.save_settings(silent=True)
            self.log("配置已保存。")

    def _sync_inputs_from_config(self) -> None:
        """Update UI inputs from config."""
        self.utorrent_exe_input.setText(self.config.utorrent_executable)
        self.webui_url_input.setText(self.config.utorrent_webui_url)
        self.webui_user_input.setText(self.config.utorrent_webui_username)
        self.webui_password_input.setText(self.config.utorrent_webui_password)

    def _build_main_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        # Drag and drop hint
        self._drop_hint = QLabel("拖放文件或文件夹到此处，或点击下方按钮选择")
        self._drop_hint.setAlignment(Qt.AlignCenter)
        self._drop_hint.setStyleSheet(
            "QLabel {"
            "  border: 2px dashed #aaa;"
            "  border-radius: 8px;"
            "  padding: 20px;"
            "  color: #888;"
            "  font-size: 14px;"
            "}"
        )
        self._drop_hint.setMinimumHeight(80)
        layout.addWidget(self._drop_hint)

        choose_layout = QHBoxLayout()
        self.path_label = QLabel("尚未选择资源")
        choose_file_button = QPushButton("选择文件")
        choose_folder_button = QPushButton("选择文件夹")
        choose_file_button.clicked.connect(self.choose_file)
        choose_folder_button.clicked.connect(self.choose_folder)
        choose_layout.addWidget(choose_file_button)
        choose_layout.addWidget(choose_folder_button)
        choose_layout.addWidget(self.path_label, 1)
        layout.addLayout(choose_layout)

        self.summary_label = QLabel("文件数量：0，总大小：0 B")
        layout.addWidget(self.summary_label)

        form_group = QGroupBox("资源信息")
        form = QFormLayout(form_group)
        self.title_input = QLineEdit()
        self.subtitle_input = QLineEdit()
        self.description_input = QPlainTextEdit()
        self.description_input.setMinimumHeight(160)
        self.category_input = QComboBox()
        for value, label in CATEGORIES:
            self.category_input.addItem(label, value)
        self.tags_input = QLineEdit()
        self.tags_input.setPlaceholderText("多个标签用空格分隔")
        form.addRow("标题", self.title_input)
        form.addRow("副标题", self.subtitle_input)
        form.addRow("简介", self.description_input)
        form.addRow("分类", self.category_input)
        form.addRow("标签", self.tags_input)
        layout.addWidget(form_group)

        self.compliance_checkbox = QCheckBox("我确认上传内容符合校园网和站点规则，不包含违法违规或未授权传播内容。")
        layout.addWidget(self.compliance_checkbox)

        action_layout = QHBoxLayout()
        self.seed_button = QPushButton("一键做种")
        self.seed_button.clicked.connect(self.start_seed)
        action_layout.addStretch(1)
        action_layout.addWidget(self.seed_button)
        layout.addLayout(action_layout)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        layout.addWidget(self.progress)

        self.log_box = LogBox()
        layout.addWidget(self.log_box)
        return page

    def _build_settings_tab(self) -> QWidget:
        page = QWidget()
        layout = QFormLayout(page)
        settings_actions = QHBoxLayout()
        auto_config_button = QPushButton("一键配置")
        save_settings_button = QPushButton("保存设置")
        auto_config_button.clicked.connect(self.auto_configure)
        save_settings_button.clicked.connect(self.save_settings)
        settings_actions.addWidget(auto_config_button)
        settings_actions.addWidget(save_settings_button)
        settings_actions.addStretch(1)
        layout.addRow("", settings_actions)

        self.site_url_input = QLineEdit(self.config.site_base_url)
        self.tracker_input = QLineEdit(self.config.tracker_url)
        tracker_actions = QHBoxLayout()
        tracker_from_sample_button = QPushButton("从测试种子读取")
        tracker_from_file_button = QPushButton("选择种子读取")
        tracker_from_sample_button.clicked.connect(self.fill_tracker_from_sample)
        tracker_from_file_button.clicked.connect(self.fill_tracker_from_file)
        tracker_actions.addWidget(self.tracker_input, 1)
        tracker_actions.addWidget(tracker_from_sample_button)
        tracker_actions.addWidget(tracker_from_file_button)

        self.cookie_input = QLineEdit(self.config.cookie_header)
        self.cookie_input.setPlaceholderText("可粘贴 Cookie 请求头、curl、Set-Cookie 或浏览器 Cookie 表格")
        cookie_actions = QHBoxLayout()
        web_login_button = QPushButton("网页登录")
        paste_cookie_button = QPushButton("粘贴/规范化")
        import_cookie_button = QPushButton("导入 cookies.txt")
        test_login_button = QPushButton("检测登录")
        web_login_button.clicked.connect(self.open_web_login)
        paste_cookie_button.clicked.connect(self.paste_cookie)
        import_cookie_button.clicked.connect(self.import_cookie_file)
        test_login_button.clicked.connect(self.test_login_cookie)
        cookie_actions.addWidget(self.cookie_input, 1)
        cookie_actions.addWidget(web_login_button)
        cookie_actions.addWidget(paste_cookie_button)
        cookie_actions.addWidget(import_cookie_button)
        cookie_actions.addWidget(test_login_button)

        self.utorrent_exe_input = QLineEdit(self.config.utorrent_executable)
        utorrent_actions = QHBoxLayout()
        browse_utorrent_button = QPushButton("浏览")
        find_utorrent_button = QPushButton("自动查找")
        test_webui_button = QPushButton("检测 WebUI")
        browse_utorrent_button.clicked.connect(self.browse_utorrent)
        find_utorrent_button.clicked.connect(self.fill_utorrent_path)
        test_webui_button.clicked.connect(self.test_utorrent_webui)
        utorrent_actions.addWidget(self.utorrent_exe_input, 1)
        utorrent_actions.addWidget(browse_utorrent_button)
        utorrent_actions.addWidget(find_utorrent_button)
        utorrent_actions.addWidget(test_webui_button)

        self.webui_url_input = QLineEdit(self.config.utorrent_webui_url)
        self.webui_user_input = QLineEdit(self.config.utorrent_webui_username)
        self.webui_password_input = QLineEdit(self.config.utorrent_webui_password)
        self.webui_password_input.setEchoMode(QLineEdit.Password)
        layout.addRow("金凤站点地址", self.site_url_input)
        layout.addRow("Tracker 地址", tracker_actions)
        layout.addRow("登录 Cookie", cookie_actions)
        layout.addRow("µTorrent 路径", utorrent_actions)
        layout.addRow("µTorrent WebUI", self.webui_url_input)
        layout.addRow("WebUI 用户名", self.webui_user_input)
        layout.addRow("WebUI 密码", self.webui_password_input)

        for line_edit in (
            self.site_url_input,
            self.tracker_input,
            self.cookie_input,
            self.utorrent_exe_input,
            self.webui_url_input,
            self.webui_user_input,
            self.webui_password_input,
        ):
            line_edit.editingFinished.connect(lambda line_edit=line_edit: self.save_settings(silent=True))
        return page

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

    def paste_cookie(self) -> None:
        text, ok = QInputDialog.getMultiLineText(
            self,
            "粘贴 Cookie",
            "请从浏览器开发者工具复制 phoenix.stu.edu.cn 的 Cookie 请求头，或复制 Cookie 表格。",
            self.cookie_input.text(),
        )
        if not ok:
            return
        cookie = normalize_cookie_header(text)
        self.cookie_input.setText(cookie)
        self.log("已规范化 Cookie 文本。")
        self.save_settings(silent=True)

    def import_cookie_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "导入 Netscape cookies.txt", filter="Text files (*.txt);;All files (*)")
        if not path:
            return
        try:
            cookie = cookie_header_from_netscape_file(Path(path))
        except Exception as exc:
            QMessageBox.warning(self, "导入 Cookie 失败", str(exc))
            return
        if not cookie:
            QMessageBox.warning(self, "导入 Cookie 失败", "文件中没有找到 phoenix.stu.edu.cn 的 Cookie。")
            return
        self.cookie_input.setText(cookie)
        self.log("已从 cookies.txt 导入金凤 Cookie。")
        self.save_settings(silent=True)

    def open_web_login(self) -> None:
        self._sync_config_from_inputs()
        dialog = LoginDialog(self.config.site_base_url, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self.cookie_input.setText(dialog.cookie_header)
        self.save_settings(silent=True)
        self.log("已从网页登录窗口保存登录状态。")
        QMessageBox.information(self, "已保存登录状态", "网页登录状态已保存，下次打开助手会自动沿用。")

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
        self.log("µTorrent WebUI 检测通过。")
        QMessageBox.information(self, "WebUI 可用", "µTorrent WebUI 已连接成功，设置已保存。")

    def auto_configure(self) -> None:
        messages: list[str] = []
        if not self.tracker_input.text().strip():
            tracker = discover_tracker_from_default_sample()
            if tracker:
                self.tracker_input.setText(tracker)
                messages.append("已读取 Tracker")
            else:
                messages.append("未找到测试种子 Tracker")

        if not self.utorrent_exe_input.text().strip():
            utorrent_path = find_utorrent_executable()
            if utorrent_path is not None:
                self.utorrent_exe_input.setText(str(utorrent_path))
                messages.append("已找到 µTorrent")
            else:
                messages.append("未找到 µTorrent")

        if not self.site_url_input.text().strip():
            self.site_url_input.setText(AppConfig().site_base_url)

        self.save_settings(silent=True)
        summary = "；".join(messages) if messages else "设置已保存"
        self.log(f"一键配置完成：{summary}")
        QMessageBox.information(self, "一键配置完成", summary)

    def test_login_cookie(self) -> None:
        self._sync_config_from_inputs()
        if not self.config.cookie_header:
            QMessageBox.warning(self, "缺少 Cookie", "请先粘贴或导入登录 Cookie。")
            return
        try:
            PhoenixClient(self.config).fetch_upload_form()
        except Exception as exc:
            QMessageBox.warning(self, "检测失败", f"无法打开上传页，请确认 Cookie 是否仍有效。\n\n{exc}")
            return
        self.save_settings(silent=True)
        self.log("登录 Cookie 检测通过，已保存。")
        QMessageBox.information(self, "检测通过", "Cookie 可以访问上传页，已保存到本机配置。")

    def save_settings(self, silent: bool = False) -> None:
        self._sync_config_from_inputs()
        path = save_app_config(self.config)
        if not silent:
            QMessageBox.information(self, "已保存", f"设置已保存到：\n{path}")
        self.log(f"设置已保存：{path}")

    def _sync_config_from_inputs(self) -> None:
        self.config.site_base_url = self.site_url_input.text().strip() or AppConfig().site_base_url
        self.config.tracker_url = self.tracker_input.text().strip()
        self.config.cookie_header = normalize_cookie_header(self.cookie_input.text())
        self.cookie_input.setText(self.config.cookie_header)
        self.config.utorrent_executable = self.utorrent_exe_input.text().strip()
        self.config.utorrent_webui_url = self.webui_url_input.text().strip() or AppConfig().utorrent_webui_url
        self.config.utorrent_webui_username = self.webui_user_input.text().strip()
        self.config.utorrent_webui_password = self.webui_password_input.text()

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
        self.subtitle_input.setText(self.draft.subtitle)
        self.description_input.setPlainText(self.draft.description)
        self.tags_input.setText(" ".join(self.draft.tags))
        self.log(f"已选择资源：{self.draft.source_path}")

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

        self._sync_config_from_inputs()
        save_app_config(self.config)

        self.draft.title = self.title_input.text().strip()
        self.draft.subtitle = self.subtitle_input.text().strip()
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

        self.seed_button.setEnabled(False)
        self.progress.setValue(0)
        self._create_worker = CreateTorrentWorker(self.config, self.draft)
        self._create_worker.log.connect(self.log)
        self._create_worker.progress.connect(self.progress.setValue)
        self._create_worker.torrent_ready.connect(self._on_torrent_created)
        self._create_worker.failed.connect(self._on_seed_failed)
        self._create_worker.start()

    def _on_torrent_created(self, torrent_path: str) -> None:
        self.progress.setValue(100)
        self.log("种子生成完成，正在打开浏览器上传...")
        self._upload_dialog = UploadDialog(
            self.config.upload_url,
            self.draft,
            Path(torrent_path),
            self.config.cookie_header,
            self,
        )
        self._upload_dialog.upload_succeeded.connect(self._on_upload_success)
        self._upload_dialog.upload_failed.connect(self._on_upload_failed)
        self._upload_dialog.finished.connect(self._on_upload_dialog_closed)
        self._upload_dialog.open()

    def _on_upload_success(self, torrent_url: str) -> None:
        self.log(f"上传成功，种子链接：{torrent_url or '(未找到)'}")
        self._start_seeding(torrent_url)

    def _on_upload_failed(self, detail: str) -> None:
        self.log(f"上传失败：{detail}")
        self.seed_button.setEnabled(True)

    def _on_upload_dialog_closed(self) -> None:
        self._upload_dialog = None

    def _start_seeding(self, torrent_url: str) -> None:
        self._seed_worker = SeedWorker(self.config, self.draft, torrent_url)
        self._seed_worker.log.connect(self.log)
        self._seed_worker.finished_ok.connect(self._on_seed_success)
        self._seed_worker.failed.connect(self._on_seed_failed)
        self._seed_worker.start()

    def _on_seed_success(self, message: str) -> None:
        self.seed_button.setEnabled(True)
        self.log(message)
        QMessageBox.information(self, "完成", message)

    def _on_seed_failed(self, message: str) -> None:
        self.seed_button.setEnabled(True)
        self.log(f"失败：{message}")
        QMessageBox.critical(self, "失败", message)

    def log(self, message: str) -> None:
        self.log_box.append_line(message)

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
