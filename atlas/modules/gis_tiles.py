"""ГИС и ГВК: плитка «ГНТ и Кг» по скважинам (как в HTML-просмотре ГИС-контроля).

На скважину и пачку один график: столбцы ГНТ (= hг эф, м) по сезонам и линия Кг (= Кг ср.взв, %) на правой оси.
Столбцы красятся по фазе: закачка (осенний замер, конец закачки) — голубой, отбор (весенний, конец отбора) — красный.
В сезоне берётся последний замер пачки (другой выбирается исключением лишних точек). Границы осей можно задать вручную,
пусто — автоматически; решает инженер, автоматика — только подсказка.
Таблица — ГНТ, Кг и их изменение к предыдущему выбранному сезону.
"""
from __future__ import annotations

import math
from typing import Any

import pandas as pd

from ..contract import Axis, Band, Chart, Column, ParamError, Series, Table, TableAction
from . import gis_an_tables as seasons_of

COMMENTS_KEY = 'gis_comments'      # ручные комментарии к столбцам плитки в настройках проекта: «скважина|пачка|сезон» -> текст
COMMENTS_JOURNAL = 'Комментарии к плитке ГИС'
HINT = 'Не исследован, ГНТ не выявлены, Технические причины'
IN_COLOR, OUT_COLOR = '#9FC7E6', '#E57373'
PHASES = (('осень', 'ГНТ — закачка', IN_COLOR), ('весна', 'ГНТ — отбор', OUT_COLOR))


def bound(text: Any, label: str) -> float | None:
    """Граница оси из текста («12,5»); пусто — автоматически."""
    value = str(text if text is not None else '').strip().replace(',', '.')
    if not value:
        return None
    try:
        number = float(value)
    except ValueError:
        raise ValueError(f'«{label}»: ожидается число или пусто (автоматически)') from None
    if not math.isfinite(number):
        raise ValueError(f'«{label}»: ожидается число или пусто (автоматически)')
    return number


def axis_range(params: dict[str, Any], prefix: str, label: str) -> tuple[float | None, float | None]:
    low, high = bound(params.get(f'{prefix}_min'), f'{label}, от'), bound(params.get(f'{prefix}_max'), f'{label}, до')
    if low is not None and high is not None and low >= high:
        raise ValueError(f'Ось «{label}»: значение «от» должно быть меньше значения «до»')
    return low, high


def caption(label: str) -> str:
    """«весна 2025» → «Отбор 2024/25», «осень 2025» → «Закачка 2025»."""
    kind, year = seasons_of.split(label)
    return f'Отбор {year - 1}/{year % 100:02d}' if kind == seasons_of.SPRING else f'Закачка {year}'


def bands(labels: list[str]) -> list[Band]:
    """Годы над столбцами: подряд идущие сезоны одного года («весна 2025» и «осень 2025» — 2025); нечётные годы на сером."""
    out: list[Band] = []
    for i, label in enumerate(labels):
        year = seasons_of.split(label)[1]
        if out and out[-1].label == str(year):
            out[-1].last = i
        else:
            out.append(Band(i, i, str(year), year % 2 == 1))
    return out


def season_values(packs: pd.DataFrame, wells: list[str], pack_names: list[str], labels: list[str]) -> pd.DataFrame:
    """Строка на (скважина, пачка, сезон): ГНТ, Кг в % и точка замера — по последнему замеру сезона."""
    part = seasons_of.seasoned(packs)
    part = part[part['well'].isin(wells) & part['season'].isin(labels)]
    if pack_names:
        part = part[part['pack'].isin(pack_names)]
    last = seasons_of._last(part, ['well', 'pack', 'season'])
    out = pd.DataFrame({'well': last['well'], 'pack': last['pack'], 'season': last['season'], 'date': last['date'],
                        'gnt': pd.to_numeric(last['h_eff_m'], errors='coerce'),
                        'kg': pd.to_numeric(last['kg_avg'], errors='coerce') * 100})
    if '_point_id' in last:
        out['_point_id'] = last['_point_id']
    return out.reset_index(drop=True)


def comment_key(well: str, pack: str, label: str) -> str:
    return f'{well}|{pack}|{label}'


def chart(well: str, pack: str, frame: pd.DataFrame, labels: list[str], params: dict[str, Any],
          comments: dict[str, str] | None = None) -> Chart:
    g_low, g_high = axis_range(params, 'gnt', 'ГНТ')
    k_low, k_high = axis_range(params, 'kg', 'Кг')
    by = frame.set_index('season')
    cats = [caption(label) for label in labels]
    result = Chart(f'gis-tile-{well}-{pack}', f'Скважина №{well}, пачка «{pack}»: ГНТ и Кг по сезонам',
                   Axis('Сезон', scale='category', categories=cats),
                   Axis('ГНТ', 'м', from_zero=True, minimum=g_low, maximum=g_high), crosshair=True,
                   y2=Axis('Кг', '%', minimum=k_low, maximum=k_high), bands=bands(labels))
    gnt = [float(by.at[s, 'gnt']) if s in by.index and pd.notna(by.at[s, 'gnt']) else None for s in labels]
    for phase, name, color in PHASES:
        values = [v if seasons_of.split(s)[0] == phase else None for s, v in zip(labels, gnt)]
        if any(v is not None for v in values):
            result.series.append(Series(name, cats, values, 'bar', stack='gnt', color=color, group='ГНТ',
                                        labels=[f'{v:g}' if v is not None else '' for v in values]))
    kg = [float(by.at[s, 'kg']) if s in by.index and pd.notna(by.at[s, 'kg']) else None for s in labels]
    if any(v is not None for v in kg):
        result.series.append(Series('Кг', cats, kg, 'line', axis='y2', markers=True, color='#e11d48',
                                    labels=[f'{v:g}' if v is not None else '' for v in kg]))
    notes = [(i, (comments or {}).get(comment_key(well, pack, s), '')) for i, s in enumerate(labels)]
    notes = [(i, text) for i, text in notes if text]
    if notes:      # подпись инженера на месте столбца (нет значения, ноль или своя пометка)
        result.series.append(Series('Комментарии', [cats[i] for i, _ in notes], [0.0] * len(notes), 'points', legend=False,
                                    color='#555555', symbol='diamond', labels=[t for _, t in notes], captions=[t for _, t in notes]))
    return result


def delta(a: Any, b: Any) -> float | None:
    return None if pd.isna(a) or pd.isna(b) else round(float(b) - float(a), 4)


def table(frame: pd.DataFrame, labels: list[str]) -> Table:
    """ГНТ, ΔГНТ, Кг, ΔКг: Δ — к предыдущему выбранному сезону той же скважины и пачки."""
    rows = []
    for (well, pack), part in frame.groupby(['well', 'pack'], sort=True):
        by = part.set_index('season')
        prev = None
        for label in labels:
            row = by.loc[label] if label in by.index else None
            gnt, kg = (row['gnt'], row['kg']) if row is not None else (math.nan, math.nan)
            rows.append({'well': well, 'pack': pack, 'season': caption(label), 'gnt': gnt,
                         'd_gnt': delta(prev[0], gnt) if prev else None, 'kg': kg,
                         'd_kg': delta(prev[1], kg) if prev else None})
            prev = (gnt, kg)
    cols = ['well', 'pack', 'season', 'gnt', 'd_gnt', 'kg', 'd_kg']
    return Table('gis-tile-table', 'ГНТ, Кг и их изменение по сезонам', pd.DataFrame(rows, columns=cols),
                 [Column('well', 'Скважина'), Column('pack', 'Пачка'), Column('season', 'Сезон'),
                  Column('gnt', 'ГНТ, м', decimals=2), Column('d_gnt', 'ΔГНТ, м', decimals=2),
                  Column('kg', 'Кг, %', decimals=1), Column('d_kg', 'ΔКг, % п.п.', decimals=1)],
                 note='Δ — к предыдущему выбранному сезону; пусто, если в одном из сезонов нет значения.')


def comment_rows(frame: pd.DataFrame, labels: list[str], comments: dict[str, str]) -> pd.DataFrame:
    """Сезоны без значения или с нулём по ГНТ или Кг — место для ручного комментария; уже введённые остаются в списке."""
    rows = []
    for (well, pack), part in frame.groupby(['well', 'pack'], sort=True):
        by = part.set_index('season')
        for label in labels:
            gnt, kg = (by.at[label, 'gnt'], by.at[label, 'kg']) if label in by.index else (math.nan, math.nan)
            key = comment_key(str(well), str(pack), label)
            if pd.isna(gnt) or gnt == 0 or pd.isna(kg) or kg == 0 or comments.get(key):
                rows.append({'key': key, 'well': well, 'pack': pack, 'season': caption(label), 'gnt': gnt, 'kg': kg,
                             'comment': comments.get(key, '')})
    return pd.DataFrame(rows, columns=['key', 'well', 'pack', 'season', 'gnt', 'kg', 'comment'])


def comments_table(frame: pd.DataFrame) -> Table:
    action = TableAction('assign', None, 'key', 'Сохранить комментарии', target='gis-comments', fields=('comment',),
                         editable=('comment',), journal=COMMENTS_JOURNAL, submit='changed')
    return Table('gis-tile-comments', 'Комментарии к столбцам без значения', frame,
                 [Column('well', 'Скважина'), Column('pack', 'Пачка'), Column('season', 'Сезон'),
                  Column('gnt', 'ГНТ, м', decimals=2), Column('kg', 'Кг, %', decimals=1), Column('comment', 'Комментарий')],
                 note=f'Сезоны, где нет ГНТ или Кг либо значение нулевое. Подпись ставите вы: например «{HINT}» или свой текст; '
                      'она появится на графике. Пустое значение снимает комментарий.', action=action)


def with_comments(settings: Any, changes: Any) -> dict[str, Any]:
    """Настройки проекта с комментариями плитки. Пустой текст снимает комментарий."""
    if not isinstance(changes, dict) or not changes:
        raise ParamError('Нет изменений для сохранения')
    out = dict(settings)
    saved = dict(out.get(COMMENTS_KEY) or {})
    for key, value in changes.items():
        text = str((value.get('comment') if isinstance(value, dict) else value) or '').strip()[:200]
        if text:
            saved[str(key)] = text
        else:
            saved.pop(str(key), None)
    out[COMMENTS_KEY] = saved
    return out
