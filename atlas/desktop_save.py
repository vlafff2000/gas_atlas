"""Сохранение файлов из окна приложения (pywebview): системное окно «Сохранить как».

WebView2 на Windows часто молча глушит скачивание blob-ссылок, поэтому веб-часть (desktopDownload.ts)
отдаёт файл сюда. Если окно выбора недоступно, файл кладётся в папку «Загрузки».
"""
from __future__ import annotations

import base64
import os
from typing import Any, Dict, Optional


def downloads_dir() -> str:
    path = os.path.join(os.path.expanduser("~"), "Downloads")
    return path if os.path.isdir(path) else os.path.expanduser("~")


def unique_path(folder: str, name: str) -> str:
    base, ext = os.path.splitext(name)
    path, n = os.path.join(folder, name), 1
    while os.path.exists(path):
        path = os.path.join(folder, "%s (%d)%s" % (base, n, ext))
        n += 1
    return path


def clean_name(name: str) -> str:
    name = os.path.basename(str(name).replace("\\", "/")).strip().strip(".")
    return "".join("_" if c in '<>:"|?*' or ord(c) < 32 else c for c in name) or "atlas"


class SaveApi:
    """js_api окна: window.pywebview.api.save_file(name, base64)."""

    def __init__(self) -> None:
        self._window: Optional[Any] = None

    def bind(self, window: Any) -> None:
        self._window = window

    def _ask(self, name: str) -> Optional[str]:
        import webview

        kind = getattr(getattr(webview, "FileDialog", None), "SAVE", None) or webview.SAVE_DIALOG
        ext = os.path.splitext(name)[1].lstrip(".")
        types = ("%s (*.%s)" % (ext.upper(), ext), "Все файлы (*.*)") if ext else ()
        answer = self._window.create_file_dialog(kind, directory=downloads_dir(), save_filename=name, file_types=types)
        if not answer:
            return None
        return answer if isinstance(answer, str) else answer[0]

    def save_file(self, name: str, data: str) -> Dict[str, Any]:
        name = clean_name(name)
        try:
            raw = base64.b64decode(data)
        except Exception as error:
            return {"ok": False, "error": str(error)}
        try:
            path = self._ask(name) if self._window is not None else unique_path(downloads_dir(), name)
        except Exception:  # окно выбора не открылось: кладём в «Загрузки»
            path = unique_path(downloads_dir(), name)
        if not path:
            return {"ok": False}  # отменено пользователем
        try:
            with open(path, "wb") as f:
                f.write(raw)
        except OSError as error:
            return {"ok": False, "error": str(error)}
        return {"ok": True, "path": path}
