from __future__ import annotations

import logging
import sys
import webbrowser
from pathlib import Path

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
from phoenix_helper.phoenix.discovery import discover_tracker_from_default_sample, discover_tracker_from_torrent
from phoenix_helper.torrent.creator import create_torrent, recommended_piece_length
from phoenix_helper.utils.paths import safe_filename, unique_path
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

SELENIUM_PROFILE_DIR = str(Path.home() / ".phoenix_helper" / "selenium_profile")


def _find_selenium_python() -> str:
    """Find a Python executable that can run Selenium without OpenSSL issues."""
    import shutil

    for candidate in [
        r"D:\Anaconda\python.exe",
        r"C:\Anaconda\python.exe",
        r"C:\ProgramData\Anaconda3\python.exe",
        str(Path.home() / "Anaconda3" / "python.exe"),
        str(Path.home() / "miniconda3" / "python.exe"),
    ]:
        if Path(candidate).exists():
            return candidate

    system_python = shutil.which("python3") or shutil.which("python")
    if system_python:
        return system_python

    return sys.executable


def _find_script(name: str) -> Path:
    """Find a bundled script file."""
    if getattr(sys, 'frozen', False):
        p = Path(sys._MEIPASS) / "scripts" / name
    else:
        p = Path(__file__).resolve().parents[2] / "scripts" / name
    if p.exists():
        return p
    p = Path(f"scripts/{name}")
    if p.exists():
        return p
    raise FileNotFoundError(f"找不到脚本：{name}")


class SeedWorker(QThread):
    """Full seed workflow: create torrent → browser upload → download final → open µTorrent."""
    log = Signal(str)
    finished_ok = Signal(str, str)  # (message, detail_url)
    failed = Signal(str)

    def __init__(self, config: AppConfig, draft: ResourceDraft) -> None:
        super().__init__()
        self.config = config
        self.draft = draft

    def run(self) -> None:
        try:
            self.config.ensure_directories()

            # Step 1: Create torrent
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

            # Step 2: Upload via Selenium and download site torrent
            self.log.emit("正在上传...")
            detail_url, final_torrent_path = self._browser_upload(torrent_path)
            if not detail_url:
                self.failed.emit("浏览器上传失败，未获取到详情页链接。")
                return
            if not final_torrent_path or not Path(final_torrent_path).exists():
                self.failed.emit("种子文件下载失败。")
                return
            self.log.emit(f"上传成功，详情页：{detail_url}")
            self.log.emit(f"站点种子已下载：{final_torrent_path}")

            # Step 4: Open µTorrent
            final_torrent = Path(final_torrent_path)
            save_path = self.draft.source_path.parent if self.draft.source_path.is_file() else self.draft.source_path
            self.log.emit(f"正在打开 µTorrent，下载目录：{save_path}")
            utorrent = UTorrentClient(UTorrentConfig(
                executable=self.config.utorrent_executable,
                webui_url=self.config.utorrent_webui_url,
                username=self.config.utorrent_webui_username,
                password=self.config.utorrent_webui_password,
            ))
            utorrent.open_torrent(final_torrent, save_path=save_path)
            self.log.emit("µTorrent 已启动，等待做种...")

            self.finished_ok.emit(
                "µTorrent 已打开种子文件，下载完成后会自动做种。\n请保持 µTorrent 运行。",
                detail_url,
            )
        except Exception as exc:
            self.failed.emit(str(exc))

    def _browser_upload(self, torrent_path: Path) -> tuple[str, str]:
        """Run Selenium browser upload. Returns (detail_url, saved_torrent_path)."""
        import subprocess

        script_path = _find_script("browser_upload.py")
        python_exe = _find_selenium_python()

        cmd = [
            python_exe, str(script_path),
            self.config.upload_url,
            str(torrent_path.resolve()),
            self.draft.title,
            self.draft.subtitle or "",
            self.draft.description or "",
            self.draft.category or "0",
            " ".join(self.draft.tags) if self.draft.tags else "",
            "--profile-dir", SELENIUM_PROFILE_DIR,
        ]

        self.log.emit("浏览器上传中...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        for line in result.stderr.splitlines():
            self.log.emit(line)

        if result.returncode != 0:
            raise RuntimeError(f"浏览器上传失败（退出码 {result.returncode}）")

        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        detail_url = ""
        torrent_path = ""
        for line in lines:
            if line.startswith("http"):
                if not detail_url:
                    detail_url = line
            elif line.endswith(".torrent") or "tmp" in line.lower():
                torrent_path = line
        return detail_url, torrent_path


class LoginWorker(QThread):
    """Run browser login script in a background thread."""
    log = Signal(str)
    finished_ok = Signal()
    failed = Signal(str)

    def __init__(self, site_url: str) -> None:
        super().__init__()
        self.site_url = site_url

    def run(self) -> None:
        import subprocess

        try:
            script_path = _find_script("browser_login.py")
            python_exe = _find_selenium_python()

            cmd = [python_exe, str(script_path), self.site_url, SELENIUM_PROFILE_DIR]
            self.log.emit("正在打开浏览器，请在窗口中登录...")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=360)

            for line in result.stderr.splitlines():
                self.log.emit(line)

            if result.returncode != 0:
                self.failed.emit("登录失败或超时。")
                return

            self.finished_ok.emit()
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
        self._seed_worker: SeedWorker | None = None
        self._login_worker: LoginWorker | None = None
        self._build_ui()
        self.log(f"已加载本机配置：{user_config_path()}")
        self._check_first_run()
        self._update_login_status()

    def _build_ui(self) -> None:
        tabs = QTabWidget()
        tabs.addTab(self._build_main_tab(), "一键做种")
        tabs.addTab(self._build_settings_tab(), "设置")
        self.setCentralWidget(tabs)

    def _check_first_run(self) -> None:
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
        self.utorrent_exe_input.setText(self.config.utorrent_executable)
        self.webui_url_input.setText(self.config.utorrent_webui_url)
        self.webui_user_input.setText(self.config.utorrent_webui_username)
        self.webui_password_input.setText(self.config.utorrent_webui_password)

    def _build_main_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

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

        # Login credentials section
        login_layout = QHBoxLayout()
        self._login_status_label = QLabel("未配置")
        self._login_status_label.setStyleSheet("color: #E65100;")
        login_btn = QPushButton("配置登录")
        login_btn.clicked.connect(self._start_login)
        clear_login_btn = QPushButton("清除")
        clear_login_btn.clicked.connect(self._clear_login)
        login_layout.addWidget(self._login_status_label, 1)
        login_layout.addWidget(login_btn)
        login_layout.addWidget(clear_login_btn)

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
        layout.addRow("登录凭证", login_layout)
        layout.addRow("µTorrent 路径", utorrent_actions)
        layout.addRow("µTorrent WebUI", self.webui_url_input)
        layout.addRow("WebUI 用户名", self.webui_user_input)
        layout.addRow("WebUI 密码", self.webui_password_input)

        for line_edit in (
            self.site_url_input,
            self.tracker_input,
            self.utorrent_exe_input,
            self.webui_url_input,
            self.webui_user_input,
            self.webui_password_input,
        ):
            line_edit.editingFinished.connect(lambda line_edit=line_edit: self.save_settings(silent=True))
        return page

    # --- Login credential management ---

    def _update_login_status(self) -> None:
        """Update the login status label based on whether a profile exists."""
        profile = Path(SELENIUM_PROFILE_DIR)
        has_login = profile.exists() and any(profile.rglob("Cookies"))
        if has_login:
            self._login_status_label.setText("已配置")
            self._login_status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        else:
            self._login_status_label.setText("未配置")
            self._login_status_label.setStyleSheet("color: #E65100;")

    def _start_login(self) -> None:
        """Open Selenium browser for user to log in."""
        self._login_worker = LoginWorker(self.config.site_base_url)
        self._login_worker.log.connect(self.log)
        self._login_worker.finished_ok.connect(self._on_login_success)
        self._login_worker.failed.connect(self._on_login_failed)
        self._login_worker.start()
        self.log("正在打开浏览器进行登录配置...")

    def _on_login_success(self) -> None:
        self._update_login_status()
        self.log("登录凭证已保存。")
        QMessageBox.information(self, "登录成功", "登录凭证已保存，现在可以使用一键做种功能。")

    def _on_login_failed(self, message: str) -> None:
        self._update_login_status()
        self.log(f"登录失败：{message}")
        QMessageBox.warning(self, "登录失败", message)

    def _clear_login(self) -> None:
        """Clear saved login credentials."""
        import shutil
        profile = Path(SELENIUM_PROFILE_DIR)
        if profile.exists():
            shutil.rmtree(profile, ignore_errors=True)
            self.log("已清除登录凭证。")
        self._update_login_status()

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

        # Check login credentials
        profile = Path(SELENIUM_PROFILE_DIR)
        if not profile.exists() or not any(profile.rglob("Cookies")):
            QMessageBox.warning(
                self, "未配置登录",
                "请先在「设置」页面配置登录凭证，然后再使用一键做种功能。"
            )
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
        self.progress.setRange(0, 0)
        self._seed_worker = SeedWorker(self.config, self.draft)
        self._seed_worker.log.connect(self.log)
        self._seed_worker.finished_ok.connect(self._on_seed_success)
        self._seed_worker.failed.connect(self._on_seed_failed)
        self._seed_worker.start()

    def _on_seed_success(self, message: str, detail_url: str) -> None:
        self.seed_button.setEnabled(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self.statusBar().clearMessage()
        self.log("做种完成！")

        # Show dialog with two buttons
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

    def save_settings(self, silent: bool = False) -> None:
        self._sync_config_from_inputs()
        path = save_app_config(self.config)
        if not silent:
            QMessageBox.information(self, "已保存", f"设置已保存到：\n{path}")
        self.log(f"设置已保存：{path}")

    def _sync_config_from_inputs(self) -> None:
        self.config.site_base_url = self.site_url_input.text().strip() or AppConfig().site_base_url
        self.config.tracker_url = self.tracker_input.text().strip()
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
