"""ГИС: Σ(hi × Кг) по интервалам каждого исследования.

В исследовании по скважине каждый выделенный газонасыщенный интервал даёт произведение hi × Кг (Кг — газонасыщенность
интервала). Учитываются все интервалы с Кг выше нуля, в том числе с Кг 0,25 и ниже; нулевые и пустые — нет. Произведения
одного исследования и одной пачки складываются в одно число. Сезон — «осень ГГГГ» (после закачки) или «весна ГГГГ»
(после отбора): год берётся по дате замера. Интервалы без hi или Кг не считаются и попадают в предупреждение: программа не
прячет их молча, решение за инженером (исключения делаются в Атласе вручную).
Чистая математика над таблицей интервалов: интерфейса и настроек здесь нет.
"""
from __future__ import annotations

import pandas as pd

RESULT_COLUMNS = ['well', 'season', 'date', 'investigation', 'pack', 'intervals', 'hikg']


def season_label(season: str, date: pd.Timestamp) -> str:
    return f'{season} {date.year}'


def season_order(labels) -> list[str]:
    """По времени: год, внутри года весна (после отбора) раньше осени (после закачки)."""
    return sorted(labels, key=lambda label: (int(label.split()[-1]), label.split()[0] != 'весна'))


def prepare(intervals: pd.DataFrame) -> pd.DataFrame:
    """Колонка «season» вида «осень 2024» и «investigation» (номер исследования или дата, если номера нет).
    Вызывать один раз на сырую таблицу: повторный вызов перепишет сезон."""
    out = intervals.copy()
    out['season'] = [season_label(str(s), d) for s, d in zip(out['season'], out['date'])]
    if 'investigation' not in out:
        out['investigation'] = out['date'].dt.strftime('%Y-%m-%d')
    return out


def products(intervals: pd.DataFrame) -> pd.DataFrame:
    """Строка на интервал: hi × Кг там, где Кг выше нуля и заданы оба числа; иначе NaN."""
    hi = pd.to_numeric(intervals['hi_m'], errors='coerce')
    kg = pd.to_numeric(intervals['kg'], errors='coerce')
    out = intervals.copy()
    out['product'] = (hi * kg).where((kg > 0) & hi.notna())
    return out


def sums(prepared: pd.DataFrame) -> pd.DataFrame:
    """Σ(hi × Кг) по исследованию и пачке: строка на (скважина, сезон, исследование, пачка). Вход — после prepare()."""
    counted = products(prepared)
    keys = ['well', 'season', 'date', 'investigation', 'pack']
    grouped = counted.groupby(keys, dropna=False)
    out = grouped.agg(intervals=('product', 'count'), hikg=('product', 'sum')).reset_index()
    return out[RESULT_COLUMNS].sort_values(['well', 'date', 'pack'], kind='stable').reset_index(drop=True)


def skipped(prepared: pd.DataFrame) -> int:
    """Сколько интервалов не вошло в расчёт: нет hi или Кг (Кг ноль — не пропуск, а вклад ноль)."""
    hi = pd.to_numeric(prepared['hi_m'], errors='coerce')
    kg = pd.to_numeric(prepared['kg'], errors='coerce')
    return int((hi.isna() | kg.isna()).sum())
