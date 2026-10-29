"""Фильтр скважин проекта: группы и скважины, сквозные для всех модулей Атласа.

Хранится в настройках проекта (``well_filter``: ``{groups, wells}``), поэтому у каждого проекта свой.
Пусто — скважины не ограничены. Группы и скважины пересекаются (логика «И», как в ``well_sets.scoped``).
Фильтр применяется к данным проекта до расчёта модуля: модули видят только отобранные скважины.
Решение за инженером: программа только показывает, сколько скважин скрыто фильтром; меняет фильтр инженер.
"""
from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from . import well_sets
from .contract import Data

KEY = 'well_filter'


def valid(value: Any) -> bool:
    """Настройка: None (фильтр снят) или словарь с необязательными списками строк ``groups`` и ``wells``."""
    if value is None:
        return True
    if not isinstance(value, dict) or not set(value) <= {'groups', 'wells'}:
        return False
    return all(isinstance(x, str) for k in ('groups', 'wells') for x in (value.get(k) or [])) \
        and all(isinstance(value.get(k) or [], list) for k in ('groups', 'wells'))


def clean(value: Any) -> dict[str, list[str]] | None:
    """Нормальная форма: без повторов, в порядке выбора; пустой фильтр — None."""
    groups = list(dict.fromkeys(str(g) for g in (value or {}).get('groups') or []))
    wells = list(dict.fromkeys(str(w) for w in (value or {}).get('wells') or []))
    return {'groups': groups, 'wells': wells} if groups or wells else None


def selection(settings: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """Выбранные группы и скважины фильтра проекта (пустые списки — фильтра нет)."""
    value = settings.get(KEY) or {}
    return list(value.get('groups') or []), list(value.get('wells') or [])


def valid_tabs(value: Any) -> bool:
    """Настройка ``export_filters``: None или словарь «вкладка экспорта → фильтр скважин»."""
    return value is None or isinstance(value, dict) and all(isinstance(k, str) and len(k) <= 60 and isinstance(v, dict) and valid(v)
                                                            for k, v in value.items())


def clean_tabs(value: Any) -> dict[str, dict[str, list[str]]] | None:
    """Фильтры вкладок экспорта в нормальной форме. Поле без списка (None) не хранится — это «все»; пустой список — «ничего»."""
    out = {}
    for tab, flt in (value or {}).items():
        item = {k: list(dict.fromkeys(str(x) for x in flt[k])) for k in ('groups', 'wells') if flt.get(k) is not None}
        if item:
            out[tab] = item
    return out or None


def _subset(frame: pd.DataFrame | None, keep: set[str]) -> pd.DataFrame | None:
    if frame is None or 'well' not in frame.columns:
        return frame
    return frame[frame['well'].astype(str).isin(keep)]


def apply(data: Data) -> Data:
    """Данные проекта без скважин, скрытых фильтром. Без фильтра возвращаются как есть."""
    groups, wells = selection(data.settings)
    if not groups and not wells:
        return data
    keep, _hidden = well_sets.scoped(wells, groups, data.mapping, data.wells)
    keep = set(keep or [])
    out = Data({k: _subset(data[k], keep) for k in data}, {k: _subset(v, keep) for k, v in data.raw.items()}, data.excluded)
    out.settings, out.revision, out.mapping = data.settings, data.revision, data.mapping
    out.project, out.model_notes = data.project, list(data.model_notes)
    out.wells = [w for w in data.wells if w in keep]
    return out


def status(data: Data) -> dict[str, Any]:
    """Что видно в окне фильтра: сколько скважин проекта остаётся и сколько скрыто."""
    groups, wells = selection(data.settings)
    total = len(data.wells)
    if not groups and not wells:
        return {'groups': [], 'wells': [], 'total': total, 'shown': total, 'hidden': 0}
    scope, hidden = well_sets.scoped(wells, groups, data.mapping, data.wells)
    return {'groups': groups, 'wells': wells, 'total': total, 'shown': len(scope or []), 'hidden': hidden}
