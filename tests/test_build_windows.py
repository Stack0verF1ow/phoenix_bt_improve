import importlib.util
from pathlib import Path


def _load_build_windows_module():
    script = Path(__file__).resolve().parents[1] / "scripts" / "build_windows.py"
    spec = importlib.util.spec_from_file_location("build_windows", script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_clean_build_environment_removes_conda_paths_and_vars() -> None:
    env = {
        "PATH": (
            r"D:\Anaconda;"
            r"D:\Anaconda\Library\bin;"
            r"D:\Anaconda\Library\mingw-w64\bin;"
            r"C:\Windows\System32;"
            r"D:\Anaconda\Scripts"
        ),
        "CONDA_PREFIX": r"D:\Anaconda",
        "CONDA_DEFAULT_ENV": "base",
        "PYTHONPATH": r"D:\Anaconda\Lib",
    }

    build_windows = _load_build_windows_module()
    cleaned = build_windows._clean_build_environment(env)

    assert cleaned["PATH"] == r"C:\Windows\System32"
    assert "CONDA_PREFIX" not in cleaned
    assert "CONDA_DEFAULT_ENV" not in cleaned
    assert "PYTHONPATH" not in cleaned


def test_clean_build_environment_removes_miniconda_and_mambaforge_paths() -> None:
    env = {
        "PATH": (
            r"C:\Miniconda3;"
            r"C:\Tools;"
            r"C:\mambaforge\Library\bin;"
            r"C:\Users\demo\AppData\Local\Programs\Python\Python312"
        ),
    }

    build_windows = _load_build_windows_module()
    cleaned = build_windows._clean_build_environment(env)

    assert cleaned["PATH"] == (
        r"C:\Tools;"
        r"C:\Users\demo\AppData\Local\Programs\Python\Python312"
    )


def test_windows_build_uses_ascii_executable_name() -> None:
    build_windows = _load_build_windows_module()

    build_windows.APP_NAME.encode("ascii")
