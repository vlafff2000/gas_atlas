"""Фильтр скважин вкладки: группы и скважины, свои у каждой вкладки (раздел и панель) Атласа.

Фильтр приходит вместе с параметрами вкладки (``params['well_filter']`` = ``{groups, wells}``): у каждой вкладки своё
состояние, включение одной вкладки на другие не влияет. Общими остаются только пресеты скважин проекта
(``well_sets``). Пусто — скважины не ограничены. Группы и скважины пересекаются (логика «И», как в ``well_sets.scoped``).
Фильтр применяется к данным проекта до расчёта вкладки: расчёт видит только отобранные скважины.
Решение за инженером: программа только показывает, сколько скважин скрыто фильтром; меняет фильтр инженер.

Настройка проекта ``well_filter`` — прежний общий фильтр: расчёты она больше не ограничивает, интерфейс лишь
подставляет её как начальный фильтр вкладки, у которой своего ещё нет.
"""
from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from . import well_sets
from .contract import Data, ParamError

KEY = 'well_filter'     # и настройка проекта (прежний общий фильтр), и ключ фильтра среди параметров вкладки


def valid(value: Any) -> bool:
    """Настройка: None (фильтр снят) или словарь с необязательными списками строк ``groups`` и ``wells``."""
    if value is None:
        return True
    if not isinstance(value, dict) or not set(value) <= {'groups', 'wells'}:
        return False
    return all(isinstance(value.get(k) or [], list) for k in ('groups', 'wells')) \
        and all(isinstance(x, str) for k in ('groups', 'wells') for x in (value.get(k) or []))


def clean(value: Any) -> dict[str, list[str]] | None:
    """Нормальная форма: без повторов, в порядке выбора; пустой фильтр — None."""
    groups = list(dict.fromkeys(str(g) for g in (value or {}).get('groups') or []))
    wells = list(dict.fromkeys(str(w) for w in (value or {}).get('wells') or []))
    return {'groups': groups, 'wells': wells} if groups or wells else None


def selection(flt: Mapping[str, Any] | None) -> tuple[list[str], list[str]]:
    """Выбранные группы и скважины фильтра (пустые списки — фильтра нет)."""
    return list((flt or {}).get('groups') or []), list((flt or {}).get('wells') or [])


def split(raw: Mapping[str, Any] | None) -> tuple[dict[str, list[str]] | None, dict[str, Any]]:
    """Параметры вкладки без фильтра и сам фильтр в нормальной форме (``None`` — не задан)."""
    rest = dict(raw or {})
    value = rest.pop(KEY, None)
    if not valid(value):
        raise ParamError('Фильтр скважин: ожидаются списки групп и скважин')
    return clean(value), rest


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


def keep_set(data: Data, flt: Mapping[str, Any] | None) -> set[str] | None:
    """Скважины, которые остаются после фильтра (``None`` — фильтра нет, остаются все)."""
    groups, wells = selection(flt)
    if not groups and not wells:
        return None
    keep, _hidden = well_sets.scoped(wells, groups, data.mapping, data.wells)
    return set(keep or [])


def apply(data: Data, flt: Mapping[str, Any] | None = None) -> Data:
    """Данные проекта без скважин, скрытых фильтром. Без фильтра возвращаются как есть."""
    groups, wells = selection(flt)
    if not groups and not wells:
        return data
    keep, _hidden = well_sets.scoped(wells, groups, data.mapping, data.wells)
    keep = set(keep or [])
    out = Data({k: _subset(data[k], keep) for k in data}, {k: _subset(v, keep) for k, v in data.raw.items()}, data.excluded)
    out.settings, out.revision, out.mapping = data.settings, data.revision, data.mapping
    out.project, out.model_notes = data.project, list(data.model_notes)
    out.wells = [w for w in data.wells if w in keep]
    return out


def status(data: Data, flt: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Что видно в окне фильтра: сколько скважин проекта остаётся и сколько скрыто."""
    groups, wells = selection(flt)
    total = len(data.wells)
    if not groups and not wells:
        return {'groups': [], 'wells': [], 'total': total, 'shown': total, 'hidden': 0}
    scope, hidden = well_sets.scoped(wells, groups, data.mapping, data.wells)
    return {'groups': groups, 'wells': wells, 'total': total, 'shown': len(scope or []), 'hidden': hidden}
