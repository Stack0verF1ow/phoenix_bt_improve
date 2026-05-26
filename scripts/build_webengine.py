"""Build the WebEngine-based version of Phoenix Helper.

Uses PyInstaller --onedir mode because Qt WebEngine resources are large
and slow to extract from a single-file exe.

Output: dist/phoenix-helper-webengine/
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
BUILD = ROOT / "build"
APP_NAME = "phoenix-helper-webengine"


def main() -> int:
    if _is_conda_python():
        print("当前 Python 来自 Conda/Anaconda，不能直接用于打包。")
        print("Conda 的 OpenSSL DLL 容易混入 PyInstaller 产物。")
        print("请运行：python scripts/build_windows_clean.py")
        return 1

    # Don't delete entire dist/ — only remove the webengine subfolder
    webengine_dist = DIST / APP_NAME
    shutil.rmtree(webengine_dist, ignore_errors=True)
    shutil.rmtree(BUILD, ignore_errors=True)

    env = _clean_build_environment(os.environ)
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--add-data",
        f"{ROOT / 'scripts' / 'browser_upload.py'}{os.pathsep}scripts",
        "--add-data",
        f"{ROOT / 'scripts' / 'browser_login.py'}{os.pathsep}scripts",
        "--add-data",
        f"{ROOT / 'scripts' / 'fetch_quota.py'}{os.pathsep}scripts",
        "--add-data",
        f"{ROOT / 'scripts' / 'driver_factory.py'}{os.pathsep}scripts",
        *(
            [
                "--add-data",
                f"{ROOT / 'scripts' / 'drivers'}{os.pathsep}scripts{os.sep}drivers",
            ]
            if (ROOT / "scripts" / "drivers").is_dir()
            else []
        ),
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
        "--exclude-module", "PIL",
        "--exclude-module", "tkinter",
        "--exclude-module", "unittest",
        "--name", APP_NAME,
        "--paths", str(ROOT / "src"),
        str(ROOT / "scripts" / "run_app.py"),
    ]
    result = subprocess.call(command, cwd=ROOT, env=env)
    if result == 0:
        print(f"\n构建完成：{webengine_dist}")
    return result


def _is_conda_python() -> bool:
    executable = Path(sys.executable).as_posix().lower()
    prefix = Path(sys.prefix).as_posix().lower()
    return "conda" in executable or "anaconda" in executable or "conda" in prefix or "anaconda" in prefix


def _clean_build_environment(env: Mapping[str, str]) -> dict[str, str]:
    cleaned = dict(env)
    cleaned["PATH"] = _without_conda_paths(cleaned.get("PATH", ""))
    for name in (
        "CONDA_PREFIX", "CONDA_DEFAULT_ENV", "CONDA_EXE",
        "CONDA_PYTHON_EXE", "CONDA_PROMPT_MODIFIER",
        "PYTHONPATH", "PYTHONHOME",
    ):
        cleaned.pop(name, None)
    return cleaned


def _without_conda_paths(path_value: str) -> str:
    parts = []
    for part in path_value.split(os.pathsep):
        normalized = part.replace("\\", "/").lower()
        if any(kw in normalized for kw in ("anaconda", "miniconda", "mambaforge", "conda")):
            continue
        parts.append(part)
    return os.pathsep.join(parts)


if __name__ == "__main__":
    raise SystemExit(main())
