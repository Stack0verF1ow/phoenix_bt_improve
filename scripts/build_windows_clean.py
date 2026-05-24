from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from collections.abc import Sequence

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".build-venv"
PYTHON_VERSION = "3.12.13"


def main() -> int:
    uv = shutil.which("uv")
    if uv is None:
        print("未找到 uv，正在安装到当前用户环境。")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--user", "uv"], cwd=ROOT)
        uv_command = _uv_module_command()
    else:
        uv_command = [uv]

    subprocess.check_call(_uv_python_install_command(uv_command), cwd=ROOT)
    subprocess.check_call(_uv_venv_command(uv_command), cwd=ROOT)
    python = VENV / "Scripts" / "python.exe"
    subprocess.check_call([str(python), "-m", "pip", "install", "--upgrade", "pip"], cwd=ROOT)
    subprocess.check_call([str(python), "-m", "pip", "install", "-e", ".[dev]"], cwd=ROOT)
    return subprocess.call([str(python), "scripts/build_windows.py"], cwd=ROOT)


def _uv_module_command() -> list[str]:
    return [str(Path(sys.executable)), "-m", "uv"]


def _uv_python_install_command(uv_command: Sequence[str]) -> list[str]:
    return [
        *uv_command,
        "python",
        "install",
        PYTHON_VERSION,
    ]


def _uv_venv_command(uv_command: Sequence[str]) -> list[str]:
    return [
        *uv_command,
        "venv",
        str(VENV),
        "--python",
        PYTHON_VERSION,
        "--managed-python",
        "--seed",
    ]


if __name__ == "__main__":
    raise SystemExit(main())
