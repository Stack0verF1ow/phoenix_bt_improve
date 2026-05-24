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
        "--exclude-module",
        "cryptography",
        "--exclude-module",
        "OpenSSL",
        "--exclude-module",
        "urllib3.contrib.pyopenssl",
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


if __name__ == "__main__":
    raise SystemExit(main())
