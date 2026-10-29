"""Выбор скважин, общий для всех программ: список из буфера обмена, пересечение групп и скважин, пользовательские пресеты.

Пресеты проекта (группы, фонды, опорная сетка) считаются из данных проекта; пользовательские пресеты лежат в
``~/.pxg/well_presets.json`` (каталог меняется PXG_HOME) и видны во всех программах, как список папок tNav.

Пересечение: если выбраны группы и скважины, в расчёт идут скважины из групп, которые есть и в списке скважин (фильтре).
Решение за инженером: программа только показывает, сколько скважин скрыто фильтром; вручную выбор всегда меняется.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping

from .well_funds import norm

FILE = 'well_presets.json'
SEPARATORS = re.compile(r'[\r\n\t;,|]+')


def home() -> Path:
    return Path(os.environ.get('PXG_HOME') or os.path.join(os.path.expanduser('~'), '.pxg'))


def parse_list(text: str | None) -> list[str]:
    """Список скважин из текста: столбец из Excel, через запятую, точку с запятой, табуляцию или пробел.

    Порядок сохраняется, повторы убираются. «31.0» и «031» становятся «31», как в остальных программах."""
    tokens: list[str] = []
    for part in SEPARATORS.split(text or ''):
        for token in part.split():
            tokens.append(norm(token))
    return list(dict.fromkeys(t for t in tokens if t))


def match(tokens: Iterable[str], options: Iterable[str]) -> tuple[list[str], list[str]]:
    """Какие из вставленных скважин есть в списке (в порядке списка) и какие не найдены."""
    wanted = list(tokens)
    known = {norm(o): o for o in options}
    found = [known[w] for w in wanted if w in known]
    missing = [w for w in wanted if w not in known]
    return list(dict.fromkeys(found)), missing


def scoped(wells: list[str], groups: list[str], mapping: Mapping[str, Mapping[str, str]],
           known: Iterable[str]) -> tuple[list[str] | None, int]:
    """Скважины расчёта: (список или None, сколько скважин группы скрыты фильтром).

    None — ни групп, ни скважин не выбрано, ограничения нет. Иначе — пересечение выбранных групп и выбранных скважин."""
    if not groups and not wells:
        return None, 0
    pool = list(known)
    hidden = 0
    if groups:
        chosen = set(groups)
        in_groups = [w for w in pool if mapping.get(w, {}).get('group', 'Без группы') in chosen]
        pool = in_groups
        if wells:
            keep = set(wells)
            pool = [w for w in in_groups if w in keep]
            hidden = len(in_groups) - len(pool)
        return pool, hidden
    keep = set(wells)
    return [w for w in pool if w in keep], 0


# --- пользовательские пресеты ---

def _read() -> list[dict[str, Any]]:
    try:
        data = json.loads((home() / FILE).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    return [p for p in data.get('presets', []) if isinstance(p, dict) and p.get('id') and isinstance(p.get('wells'), list)]


def user_presets() -> list[dict[str, Any]]:
    return [{'id': p['id'], 'kind': 'user', 'label': p.get('name', 'Без названия'), 'wells': list(p['wells'])}
            for p in _read()]


def add_user_preset(name: str, wells: Iterable[str]) -> list[dict[str, Any]]:
    name = (name or '').strip()
    if not name:
        raise ValueError('Укажите название пресета.')
    listed = [norm(w) for w in wells if str(w).strip()]
    if not listed:
        raise ValueError('В пресете нет скважин. Выберите скважины или вставьте список из буфера обмена.')
    presets = _read()
    presets.append({'id': uuid.uuid4().hex, 'name': name, 'wells': list(dict.fromkeys(listed))})
    _write(presets)
    return user_presets()


def remove_user_preset(preset_id: str) -> list[dict[str, Any]]:
    _write([p for p in _read() if p['id'] != preset_id])
    return user_presets()


def _write(presets: list[dict[str, Any]]) -> None:
    folder = home()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / FILE).write_text(json.dumps({'presets': presets}, ensure_ascii=False, indent=1), encoding='utf-8')
