"""Плитки паспорта по годам: ревизия КРУ (песок / ревизия без песка / ревизии не было) и КРС (в какой год был ремонт).

Данные — таблицы проекта ``krs_priority`` (``sand`` — сезоны с песком) и ``krs_works``; отдельной таблицы ревизий пока нет, поэтому
«ревизия по ГСП была» выводится: в сезоне песок нашли хотя бы у одной скважины группы. Это подсказка, клетка так и подписана.
Рисует плитки общая тепловая карта (``HeatMap``), своего компонента нет; значения и подписи считаются здесь, расчётов ядра нет.
"""
from __future__ import annotations

import re
from typing import Any

import pandas as pd

SEASON = re.compile(r'(\d{4})\s*[-–—]\s*(\d{4})')


def sand_seasons(text: Any) -> list[str]:
    """Сезоны из текста «2023-2024, 2025–2026» в виде «2023-2024»."""
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return []
    return [f'{a}-{b}' for a, b in SEASON.findall(str(text))]


def _span(seasons: set[str]) -> list[str]:
    """Все сезоны от первого до последнего без пропусков."""
    if not seasons:
        return []
    starts = sorted(int(s[:4]) for s in seasons)
    return [f'{y}-{y + 1}' for y in range(starts[0], starts[-1] + 1)]


def kru_tiles(priority: pd.DataFrame | None, well: str) -> dict[str, Any] | None:
    """Плитка КРУ скважины: 1 — песок в ревизии сезона, 0 — по группе ревизия была, у скважины песка нет, None — по данным ревизии не было."""
    if priority is None or priority.empty or 'sand' not in priority:
        return None
    frame = priority.assign(well=priority['well'].astype(str), seasons=priority['sand'].map(sand_seasons))
    mine = frame[frame.well.eq(str(well))]
    if mine.empty:
        return None
    columns = _span({s for row in frame.seasons for s in row})
    if not columns:
        return None
    group = str(mine.iloc[0].get('group') or '')
    own = set(mine.iloc[0].seasons)
    revised = {s for _, r in frame[frame['group'].astype(str).eq(group)].iterrows() for s in r.seasons} if group else set(own)
    cells = [1 if s in own else 0 if s in revised else None for s in columns]
    return {'columns': columns, 'cells': cells, 'group': group}


SHORT = (('замен', 'фильтр'), ('колтюбинг с', 'СКО'), ('ско', 'СКО'), ('колтюбинг', 'колтюбинг'), ('армиров', 'армиров.'))


def short_type(name: str) -> str:
    """Короткая подпись типа ремонта для клетки плитки (полное название — в таблице «Проведённые КРС»)."""
    low = name.lower()
    return next((short for key, short in SHORT if key in low), name[:10])


def krs_tiles(works: pd.DataFrame | None, well: str) -> dict[str, Any] | None:
    """Плитка КРС скважины по годам от первого до последнего ремонта в проекте: 1 — в год был ремонт (в подписи тип), 0 — нет."""
    if works is None or works.empty:
        return None
    d = works.dropna(subset=['year']).assign(well=works['well'].astype(str))
    mine = d[d.well.eq(str(well))]
    if mine.empty:
        return None
    first, last = int(mine.year.min()), int(mine.year.max())
    columns = list(range(first, last + 1))
    texts = []
    for y in columns:
        types = [short_type(str(t)) for t in mine[mine.year.astype(int).eq(y)].work_type if str(t) not in ('', 'nan', 'None')]
        texts.append(', '.join(dict.fromkeys(types)) or ('КР' if (mine.year.astype(int) == y).any() else ''))
    cells = [1 if (mine.year.astype(int) == y).any() else 0 for y in columns]
    return {'columns': [str(y) for y in columns], 'cells': cells, 'texts': texts}
