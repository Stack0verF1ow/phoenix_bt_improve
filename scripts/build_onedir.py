"""Build Phoenix Helper using .build-venv with --onedir mode.

Output: dist/phoenix-helper/
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
BUILD = ROOT / "build"
APP_NAME = "phoenix-helper-http"
VENV_PYTHON = ROOT / ".build-venv" / "Scripts" / "python.exe"


def main() -> int:
    if not VENV_PYTHON.exists():
        print(f"错误：找不到 .build-venv Python: {VENV_PYTHON}")
        print("请先创建虚拟环境：python -m venv .build-venv")
        return 1

    # Clean previous build
    app_dist = DIST / APP_NAME
    shutil.rmtree(app_dist, ignore_errors=True)
    shutil.rmtree(BUILD, ignore_errors=True)

    # Install dependencies in venv if needed
    print("检查并安装依赖...")
    subprocess.check_call([
        str(VENV_PYTHON), "-m", "pip", "install", "--quiet",
        "PySide6>=6.7,<6.8",
        "requests>=2.31",
        "beautifulsoup4>=4.12",
        "pyinstaller>=6.0",
    ])

    command = [
        str(VENV_PYTHON),
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",
        "--exclude-module", "cryptography",
        "--exclude-module", "OpenSSL",
        "--exclude-module", "urllib3.contrib.pyopenssl",
        "--exclude-module", "PySide6.Qt3DCore",
        "--exclude-module", "PySide6.Qt3DRender",
        "--exclude-module", "PySide6.Qt3DInput",
        "--exclude-module", "PySide6.Qt3DLogic",
        "--exclude-module", "PySide6.Qt3DAnimation",
        "--exclude-module", "PySide6.Qt3DExtras",
        "--exclude-module", "PySide6.QtCharts",
        "--exclude-module", "PySide6.QtGraphs",
        "--exclude-module", "PySide6.QtMultimedia",
        "--exclude-module", "PySide6.QtMultimediaWidgets",
        "--exclude-module", "PySide6.QtPdf",
        "--exclude-module", "PySide6.QtPdfWidgets",
        "--exclude-module", "PySide6.QtQuick",
        "--exclude-module", "PySide6.QtQuickWidgets",
        "--exclude-module", "PySide6.QtQuick3D",
        "--exclude-module", "PySide6.QtQml",
        "--exclude-module", "PySide6.QtQmlModels",
        "--exclude-module", "PySide6.QtShaderTools",
        "--exclude-module", "PySide6.QtDesigner",
        "--exclude-module", "PySide6.QtHelp",
        "--exclude-module", "PySide6.QtSvg",
        "--exclude-module", "PySide6.QtTest",
        "--exclude-module", "PySide6.QtUiTools",
        "--exclude-module", "PySide6.QtSql",
        "--exclude-module", "PySide6.QtSvgWidgets",
        "--exclude-module", "PySide6.QtBluetooth",
        "--exclude-module", "PySide6.QtNfc",
        "--exclude-module", "PySide6.QtPositioning",
        "--exclude-module", "PySide6.QtRemoteObjects",
        "--exclude-module", "PySide6.QtSensors",
        "--exclude-module", "PySide6.QtSerialBus",
        "--exclude-module", "PySide6.QtSerialPort",
        "--exclude-module", "PySide6.QtSpatialAudio",
        "--exclude-module", "PySide6.QtTextToSpeech",
        "--exclude-module", "PySide6.QtWebSockets",
        "--exclude-module", "PySide6.HttpServer",
        "--exclude-module", "PySide6.GrpcTools",
        "--exclude-module", "PySide6.QtStateMachine",
        "--exclude-module", "scipy",
        "--exclude-module", "numpy",
        "--exclude-module", "pandas",
        "--exclude-module", "matplotlib",
        "--exclude-module", "tkinter",
        "--exclude-module", "unittest",
        "--name", APP_NAME,
        "--paths", str(ROOT / "src"),
        "--add-data", f"{ROOT / 'src' / 'phoenix_helper' / 'ui' / 'style.qss'};phoenix_helper/ui",
        "--hidden-import", "phoenix_helper.ui.main_window",
        str(ROOT / "scripts" / "run_app.py"),
    ]

    print(f"开始打包 {APP_NAME}...")
    result = subprocess.call(command, cwd=ROOT)
    if result == 0:
        print(f"\n构建完成：{app_dist}")
        print(f"可执行文件：{app_dist / APP_NAME}.exe")
    else:
        print(f"\n构建失败，退出码：{result}")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
