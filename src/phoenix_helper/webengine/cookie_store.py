from __future__ import annotations

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWebEngineCore import QWebEngineCookieStore, QWebEngineProfile


def extract_cookies(profile: QWebEngineProfile, host: str = "phoenix.stu.edu.cn") -> str:
    """Extract cookies from a QWebEngineProfile as a 'name=value; ...' header string.

    Uses loadAllCookies() + a local QEventLoop to wait for async completion.
    """
    cookie_store: QWebEngineCookieStore = profile.cookieStore()
    collected: dict[str, str] = {}
    loop = QEventLoop()

    def on_cookie_added(cookie) -> None:
        domain = cookie.domain()
        if host not in domain:
            return
        name_bytes = cookie.name()
        value_bytes = cookie.value()
        name = name_bytes.data().decode("utf-8", errors="replace")
        value = value_bytes.data().decode("utf-8", errors="replace")
        collected[name] = value

    cookie_store.cookieAdded.connect(on_cookie_added)

    cookie_store.loadAllCookies()
    QTimer.singleShot(500, loop.quit)
    loop.exec()

    cookie_store.cookieAdded.disconnect(on_cookie_added)
    return "; ".join(f"{name}={value}" for name, value in collected.items())
