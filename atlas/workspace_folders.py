"""Общий выбор проекта (как в «Базе ПХГ»): папка проекта с подпапками «готовые» и «выгрузки».

Файл выбора — ``рабочие_папки.json`` в каталоге пользователя (``~/.pxg/``, каталог меняется PXG_HOME).
Его пишет «База ПХГ» (all_scripts, pxg_core/workspace.py); здесь он только читается. Формат: {"project": "<путь>"}.
Подпапки: ``готовые/`` (готовые файлы) и ``выгрузки/`` (данные после Базы ПХГ).
"""
from __future__ import annotations

import json
import os
from typing import Any

FILE_NAME = 'рабочие_папки.json'
SUBFOLDERS = (('ready', 'готовые', 'Готовые файлы'), ('exports', 'выгрузки', 'Данные после Базы ПХГ'))


def settings_path() -> str:
    home = os.environ.get('PXG_HOME') or os.path.join(os.path.expanduser('~'), '.pxg')
    return os.path.join(home, FILE_NAME)


def chosen_project() -> str:
    """Путь папки проекта или '' (нет файла, битый файл или пустое поле)."""
    try:
        with open(settings_path(), encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return ''
    value = data.get('project') if isinstance(data, dict) else None
    return value.strip() if isinstance(value, str) else ''


def state() -> dict[str, Any]:
    """Выбранный проект и подпапки: есть ли каждая и сколько в ней файлов (только имена, без чтения содержимого)."""
    project = chosen_project()
    folders = []
    for slot, name, label in SUBFOLDERS:
        path = os.path.join(project, name) if project else ''
        found = bool(path) and os.path.isdir(path)
        files: list[str] = []
        if found:
            try:
                files = sorted(f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f)) and not f.startswith('~$'))
            except OSError:
                found, files = False, []
        folders.append({'slot': slot, 'label': label, 'path': path, 'found': found, 'files': files})
    return {'project': project, 'folders': folders}
