from __future__ import annotations

from PySide6.QtWidgets import QTextEdit


class LogBox(QTextEdit):
    def __init__(self) -> None:
        super().__init__()
        self.setReadOnly(True)

    def append_line(self, message: str) -> None:
        self.append(message)
