from __future__ import annotations

from PySide6.QtWidgets import QTextEdit


class LogBox(QTextEdit):
    def __init__(self) -> None:
        super().__init__()
        self.setReadOnly(True)
        self._progress_line: str | None = None

    def append_line(self, message: str) -> None:
        self._progress_line = None
        self.append(message)

    def update_progress(self, message: str) -> None:
        """Replace the last line if it was a progress line, otherwise append."""
        cursor = self.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        if self._progress_line:
            # Select and replace the last line
            cursor.movePosition(cursor.MoveOperation.StartOfBlock, cursor.MoveMode.KeepAnchor)
            cursor.removeSelectedText()
            cursor.insertText(message)
        else:
            cursor.insertText('\n' + message)
        self._progress_line = message
        self.setTextCursor(cursor)
        self.ensureCursorVisible()
