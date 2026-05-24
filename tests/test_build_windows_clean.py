import importlib.util
from pathlib import Path


def _load_build_windows_clean_module():
    script = Path(__file__).resolve().parents[1] / "scripts" / "build_windows_clean.py"
    spec = importlib.util.spec_from_file_location("build_windows_clean", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_uv_venv_command_uses_managed_python() -> None:
    build_windows_clean = _load_build_windows_clean_module()

    command = build_windows_clean._uv_venv_command(["uv"])

    assert command == [
        "uv",
        "venv",
        str(build_windows_clean.VENV),
        "--python",
        build_windows_clean.PYTHON_VERSION,
        "--managed-python",
        "--seed",
    ]


def test_python_version_is_exact_patch_release() -> None:
    build_windows_clean = _load_build_windows_clean_module()

    assert build_windows_clean.PYTHON_VERSION.count(".") == 2


def test_uv_python_install_command_uses_requested_version() -> None:
    build_windows_clean = _load_build_windows_clean_module()

    command = build_windows_clean._uv_python_install_command(["uv"])

    assert command == ["uv", "python", "install", build_windows_clean.PYTHON_VERSION]


def test_uv_module_command_uses_current_python_module() -> None:
    build_windows_clean = _load_build_windows_clean_module()

    command = build_windows_clean._uv_module_command()

    assert command == [str(Path(build_windows_clean.sys.executable)), "-m", "uv"]
