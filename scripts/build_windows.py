from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
BUILD = ROOT / "build"
APP_NAME = "phoenix-helper"
REQUIRED_MODULES = ["PySide6", "requests", "bs4", "PyInstaller"]


def main() -> int:
    if _is_conda_python():
        print("当前 Python 来自 Conda/Anaconda，不能直接用于打包。")
        print("Conda 的 OpenSSL DLL 容易混入 PyInstaller 产物，导致启动时报 OPENSSL_Uplink/no OPENSSL_Applink。")
        print("请运行：python scripts/build_windows_clean.py")
        return 1

    missing = [module for module in REQUIRED_MODULES if importlib.util.find_spec(module) is None]
    if missing:
        print("缺少打包依赖：" + ", ".join(missing))
        print("请先运行：python -m pip install -e \".[dev]\"")
        return 1

    shutil.rmtree(BUILD, ignore_errors=True)
    shutil.rmtree(DIST, ignore_errors=True)
    env = _clean_build_environment(os.environ)
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--console",
        "--onefile",
        "--add-data",
        f"{ROOT / 'scripts' / 'browser_upload.py'}{os.pathsep}scripts",
        "--add-data",
        f"{ROOT / 'scripts' / 'browser_login.py'}{os.pathsep}scripts",
        "--exclude-module",
        "cryptography",
        "--exclude-module",
        "OpenSSL",
        "--exclude-module",
        "urllib3.contrib.pyopenssl",
        # Exclude unused Qt modules to reduce size
        "--exclude-module",
        "PySide6.Qt3DCore",
        "--exclude-module",
        "PySide6.Qt3DRender",
        "--exclude-module",
        "PySide6.Qt3DInput",
        "--exclude-module",
        "PySide6.Qt3DLogic",
        "--exclude-module",
        "PySide6.Qt3DAnimation",
        "--exclude-module",
        "PySide6.Qt3DExtras",
        "--exclude-module",
        "PySide6.QtCharts",
        "--exclude-module",
        "PySide6.QtGraphs",
        "--exclude-module",
        "PySide6.QtMultimedia",
        "--exclude-module",
        "PySide6.QtMultimediaWidgets",
        "--exclude-module",
        "PySide6.QtPdf",
        "--exclude-module",
        "PySide6.QtPdfWidgets",
        "--exclude-module",
        "PySide6.QtQuick",
        "--exclude-module",
        "PySide6.QtQuickWidgets",
        "--exclude-module",
        "PySide6.QtQuick3D",
        "--exclude-module",
        "PySide6.QtQml",
        "--exclude-module",
        "PySide6.QtQmlModels",
        "--exclude-module",
        "PySide6.QtShaderTools",
        "--exclude-module",
        "PySide6.QtDesigner",
        "--exclude-module",
        "PySide6.QtHelp",
        "--exclude-module",
        "PySide6.QtSvg",
        "--exclude-module",
        "PySide6.QtTest",
        "--exclude-module",
        "PySide6.QtUiTools",
        "--exclude-module",
        "PySide6.QtOpenGL",
        "--exclude-module",
        "PySide6.QtOpenGLWidgets",
        "--exclude-module",
        "PySide6.QtSql",
        "--exclude-module",
        "PySide6.QtSvgWidgets",
        "--exclude-module",
        "PySide6.QtBluetooth",
        "--exclude-module",
        "PySide6.QtNfc",
        "--exclude-module",
        "PySide6.QtPositioning",
        "--exclude-module",
        "PySide6.QtRemoteObjects",
        "--exclude-module",
        "PySide6.QtSensors",
        "--exclude-module",
        "PySide6.QtSerialBus",
        "--exclude-module",
        "PySide6.QtSerialPort",
        "--exclude-module",
        "PySide6.QtSpatialAudio",
        "--exclude-module",
        "PySide6.QtTextToSpeech",
        "--exclude-module",
        "PySide6.QtWebChannel",
        "--exclude-module",
        "PySide6.QtWebSockets",
        "--exclude-module",
        "PySide6.HttpServer",
        "--exclude-module",
        "PySide6.GrpcTools",
        "--exclude-module",
        "PySide6.QtStateMachine",
        # WebEngine removed - using system browser + bookmarklet instead
        "--exclude-module",
        "PySide6.QtWebEngineWidgets",
        "--exclude-module",
        "PySide6.QtWebEngineCore",
        "--exclude-module",
        "PySide6.QtWebEngineQuick",
        "--exclude-module",
        "scipy",
        "--exclude-module",
        "numpy",
        "--exclude-module",
        "pandas",
        "--exclude-module",
        "matplotlib",
        "--exclude-module",
        "PIL",
        "--exclude-module",
        "tkinter",
        "--exclude-module",
        "unittest",
        "--name",
        APP_NAME,
        "--paths",
        str(ROOT / "src"),
        str(ROOT / "scripts" / "run_app.py"),
    ]
    return subprocess.call(command, cwd=ROOT, env=env)


def _is_conda_python() -> bool:
    executable = Path(sys.executable).as_posix().lower()
    prefix = Path(sys.prefix).as_posix().lower()
    return "conda" in executable or "anaconda" in executable or "conda" in prefix or "anaconda" in prefix


def _clean_build_environment(env: Mapping[str, str]) -> dict[str, str]:
    cleaned = dict(env)
    cleaned["PATH"] = _without_conda_paths(cleaned.get("PATH", ""))
    for name in (
        "CONDA_PREFIX",
        "CONDA_DEFAULT_ENV",
        "CONDA_EXE",
        "CONDA_PYTHON_EXE",
        "CONDA_PROMPT_MODIFIER",
        "PYTHONPATH",
        "PYTHONHOME",
    ):
        cleaned.pop(name, None)
    return cleaned


def _without_conda_paths(path_value: str) -> str:
    parts = []
    for part in path_value.split(os.pathsep):
        normalized = part.replace("\\", "/").lower()
        if "anaconda" in normalized or "miniconda" in normalized or "mambaforge" in normalized or "conda" in normalized:
            continue
        parts.append(part)
    return os.pathsep.join(parts)


if __name__ == "__main__":
    raise SystemExit(main())
