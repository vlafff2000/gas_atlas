"""Подписи категорий оси X: переименование и перенос по ширине (общее для файлов; зеркало на экране — ``web/src/categoryLabel.ts``).

Решает инженер: имена задаются в «Формате» оси X (``category_names``: прежнее имя -> новое), перенос — ширина в знаках
(``category_wrap``, 0 — без переноса). Свой перенос строки («\\n») в имени сохраняется. Данные графика не меняются."""
from __future__ import annotations

import textwrap
from typing import Any, Mapping


def wrap(text: str, width: int) -> str:
    """Перенос по словам: строка не длиннее ``width`` знаков; слово длиннее ширины остаётся целым."""
    if not width or width < 1:
        return text
    return '\n'.join('\n'.join(textwrap.wrap(part, width, break_long_words=False, break_on_hyphens=False)) or part
                     for part in text.split('\n'))


def label(name: str, spec: Mapping[str, Any] | None) -> str:
    spec = spec or {}
    shown = (spec.get('category_names') or {}).get(name) or name
    return wrap(shown, int(spec.get('category_wrap') or 0))


def labels(categories: list[str], spec: Mapping[str, Any] | None) -> list[str]:
    return [label(str(c), spec) for c in categories]
