"""Память экспорта: последние настройки вкладок выгрузки (форма и открытая вкладка) в папке проекта (``export_form.json``).

Как пользовательские пресеты скважин (``well_sets``): отдельный файл рядом с проектом, версия данных не меняется и в журнал запись не идёт —
иначе каждый щелчок по настройке пересчитывал бы предпросмотр. Фильтры скважин вкладок хранятся отдельно (``settings.export_filters``)
и сюда не попадают. Сброс удаляет файл: вкладки возвращаются к умолчаниям.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

FILE = 'export_form.json'
MAX_BYTES = 256_000
SKIP_SUFFIXES = ('_wells', '_groups')       # фильтры скважин хранятся в проекте отдельно


def _clean(form: Any) -> dict[str, Any]:
    if not isinstance(form, dict):
        return {}
    return {k: v for k, v in form.items() if isinstance(k, str) and len(k) <= 80 and not k.endswith(SKIP_SUFFIXES)}


def read(folder: Path) -> dict[str, Any]:
    try:
        data = json.loads((folder / FILE).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'form': {}, 'tab': None}
    tab = data.get('tab') if isinstance(data, dict) else None
    return {'form': _clean(data.get('form') if isinstance(data, dict) else None), 'tab': tab if isinstance(tab, str) else None}


def write(folder: Path, form: Any, tab: Any = None) -> dict[str, Any]:
    data = {'form': _clean(form), 'tab': tab if isinstance(tab, str) and len(tab) <= 80 else None}
    text = json.dumps(data, ensure_ascii=False)
    if len(text.encode('utf-8')) > MAX_BYTES:
        raise ValueError('Настройки экспорта слишком велики, чтобы их запомнить.')
    tmp = folder / (FILE + '.tmp')
    tmp.write_text(text, encoding='utf-8')
    os.replace(tmp, folder / FILE)
    return data


def reset(folder: Path) -> None:
    try:
        (folder / FILE).unlink()
    except FileNotFoundError:
        pass
