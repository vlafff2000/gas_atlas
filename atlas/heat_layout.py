"""Раскладка тепловой карты: порядок строк и итоги. Одна логика для файла (``chart_special._heat_figure``) и экрана (зеркало ``web/src/heatLayout.ts``).

Настройки оформления: ``heat_sort`` (порядок строк: как в данных, по сумме значений, по названию), ``heat_totals`` (итог по строкам справа,
по столбцам снизу, оба) и ``heat_total`` (сумма или среднее). Итоги не окрашиваются шкалой карты и не влияют на её пределы."""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

SORTS = ('sum', 'name')
TOTALS = ('rows', 'cols', 'both')
KINDS = ('sum', 'mean')


def _natural(text: str) -> list[Any]:
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r'(\d+)', text)]


def row_order(rows: Sequence[str], values: Sequence[Sequence[float | None]], sort: str | None) -> list[int]:
    """Порядок строк: ``sum`` — по сумме значений (больше — выше), ``name`` — по названию с учётом чисел («ГСП 2» перед «ГСП 10»)."""
    idx = list(range(len(rows)))
    if sort == 'sum':
        return sorted(idx, key=lambda i: (-sum(v for v in values[i] if v is not None), i))
    if sort == 'name':
        return sorted(idx, key=lambda i: (_natural(rows[i]), i))
    return idx


def total(values: Sequence[float | None], kind: str | None) -> float | None:
    """Итог по ряду значений: сумма или среднее; пустой ряд — ``None``."""
    got = [v for v in values if v is not None]
    if not got:
        return None
    return sum(got) if kind != 'mean' else sum(got) / len(got)


def text(value: float | None) -> str:
    """Подпись итога: до одного знака после запятой, без лишних нулей."""
    return '' if value is None else f'{round(value, 1):g}'


def layout(rows: Sequence[str], values: Sequence[Sequence[float | None]], style: Mapping[str, Any]) -> dict[str, Any]:
    """``order`` — индексы строк; ``row_totals`` — итоги по строкам (в порядке ``order``) или ``None``; ``col_totals`` — итоги по столбцам или ``None``."""
    order = row_order(rows, values, style.get('heat_sort'))
    mode, kind = style.get('heat_totals'), style.get('heat_total')
    row_totals = [total(values[i], kind) for i in order] if mode in ('rows', 'both') else None
    col_totals = [total([values[i][j] for i in order], kind) for j in range(len(values[0]) if values else 0)] if mode in ('cols', 'both') else None
    return {'order': order, 'row_totals': row_totals, 'col_totals': col_totals}
