"""ГИС и ГВК: таблицы главы 5 «Авторского надзора» (5.4–5.8) по базе ГИС проекта.

5.4 — результаты исследований: интервалы с Кг, Нг и ГВК (глубина, а.о.) по сезонам; 5.5/5.7 — положение ГВК пачки по сезонам;
5.6/5.8 — относительное изменение ГВК. На каждую пачку пара «сравнение + изменение» (первая пачка — 5.5 и 5.6, вторая — 5.7 и 5.8).
Таблицы 5.3 (объём исследований) и прочие нет: в базе нет назначения и методов исследования.

Сезон — «весна ГГГГ» (замер после отбора, конец отбора ГГГГ-1/ГГ) или «осень ГГГГ» (после закачки, конец закачки ГГГГ), как
в ``gis_hikg``. Названия сезонов в заголовках и годы в названиях таблиц выводятся из выбранных сезонов, а не набираются:
меняется новый сезон или набор сезонов — меняются и подписи. Сколько сезонов взять, решает инженер: отмеченные вручную
берутся все, автоматический выбор (до четырёх сезонов, считая от нового) — только подсказка.
Δ — изменение глубины ГВК, как в отчёте: плюс — ГВК опустился (глубже), минус — поднялся. Берётся из ГВК а.о. (Δ = −Δ а.о.).
В сезоне берётся последний замер по пачке; другой замер выбирается исключением лишних точек.
"""
from __future__ import annotations

import math
from typing import Any

import pandas as pd

from ..contract import Column, Table

AUTO_SEASONS = 4          # как в отчёте: два цикла «отбор + закачка», считая от нового сезона
FIRST_NUMBER = 4          # номер первой таблицы: 5.4
SPRING, AUTUMN = 'весна', 'осень'
NO_SEASON = 'без сезона'     # замер вне сезонов (месяц не подходит и сезон не задан): не теряется, показывается серым


def season_of(season: Any, date: pd.Timestamp, keep: bool = False) -> str | None:
    """«весна 2025» / «осень 2025»: сезон из колонки, иначе по месяцу (март–май — весна, сентябрь–декабрь — осень)."""
    if pd.isna(date):
        return None
    name = str(season).strip().lower() if season is not None and not pd.isna(season) else ''
    if name not in (SPRING, AUTUMN):
        name = SPRING if date.month in (3, 4, 5) else AUTUMN if date.month in (9, 10, 11, 12) else ''
    if not name and keep:
        name = NO_SEASON
    return f'{name} {date.year}' if name else None


def split(label: str) -> tuple[str, int]:
    kind, year = label.rsplit(' ', 1)       # вид может быть из двух слов: «без сезона 2019»
    return kind, int(year)


RANK = {SPRING: 0, AUTUMN: 1}


def order(labels) -> list[str]:
    """По времени: год, внутри года весна раньше осени."""
    return sorted(set(labels), key=lambda label: (split(label)[1], RANK.get(split(label)[0], 2)))


CASES = {'nom': ('отбор', 'закачка'), 'gen': ('отбора', 'закачки'), 'ins': ('отбором', 'закачкой')}


def name_of(label: str, case: str = 'nom') -> str:
    """Название сезона для заголовка: весна 2025 → «отбор 2024/25 гг.», осень 2025 → «закачка 2025 г.».
    Падеж: nom — «отбор», gen — «отбора» (конец отбора), ins — «отбором» (Δ с отбором)."""
    kind, year = split(label)
    if kind not in (SPRING, AUTUMN):
        return f'{kind} {year} г.'
    spring, autumn = CASES[case]
    return f'{spring} {year - 1}/{year % 100:02d} гг.' if kind == SPRING else f'{autumn} {year} г.'


def span_of(labels: list[str]) -> str:
    """Годы исследований для названия таблицы: «2024/25 гг.» (от года первого сезона до года последнего), «2025 г.» для одного года."""
    first, last = split(labels[0])[1], split(labels[-1])[1]
    return f'{last} г.' if first == last else f'{first}/{last % 100:02d} гг.'


def pick(available: list[str], base: str | None, manual: list[str]) -> tuple[list[str], str | None]:
    """Сезоны таблиц и новый сезон. Отмеченные вручную берутся все; иначе — до четырёх сезонов с данными, считая от нового
    (по умолчанию самого позднего). Новый сезон — выбранный, если он есть среди сезонов, иначе последний из них."""
    chosen = order(manual) if manual else None
    if chosen is None:
        pool = order(available)
        if base and base in pool:
            pool = pool[:pool.index(base) + 1]
        chosen = pool[-AUTO_SEASONS:]
    if not chosen:
        return [], None
    return chosen, base if base in chosen else chosen[-1]


def _last(frame: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Последний замер в каждой группе ключей (по дате)."""
    return frame.sort_values('date', kind='stable').groupby(keys, sort=False).tail(1)


def seasoned(frame: pd.DataFrame, keep: bool = False) -> pd.DataFrame:
    """Колонка «season» вида «осень 2025». ``keep`` — замеры вне сезонов остаются с подписью «без сезона ГГГГ», а не отбрасываются."""
    out = frame.copy()
    seasons = out['season'] if 'season' in out else pd.Series(None, index=out.index)
    out['season'] = [season_of(s, d, keep) for s, d in zip(seasons, out['date'])]
    out['well'] = out['well'].astype(str)
    out['pack'] = out['pack'].astype(object).where(out['pack'].notna(), 'без пачки').astype(str)
    return out[out['season'].notna()]


def available(*frames: pd.DataFrame | None, keep: bool = False) -> list[str]:
    labels: set[str] = set()
    for frame in frames:
        if frame is not None and len(frame):
            labels |= set(seasoned(frame, keep)['season'])
    return order(labels)


def _num(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return math.nan
    return number if math.isfinite(number) else math.nan


def _depth(row: pd.Series) -> float:
    """Глубина ГВК: из таблицы; нет — альтитуда минус ГВК а.о. (а.о. = −(глубина − альтитуда))."""
    depth = _num(row.get('gvk_depth_m'))
    if not math.isnan(depth):
        return depth
    abs_, alt = _num(row.get('gvk_abs_m')), _num(row.get('altitude_m'))
    return alt - abs_ if not (math.isnan(abs_) or math.isnan(alt)) else math.nan


def gvk_by_season(packs: pd.DataFrame, labels: list[str]) -> dict[tuple[str, str, str], dict[str, Any]]:
    """{(скважина, пачка, сезон): глубина, а.о., Нг, Кг, подпись ГВК} по последнему замеру сезона."""
    part = seasoned(packs)
    part = part[part['season'].isin(labels)]
    out = {}
    for _, row in _last(part, ['well', 'pack', 'season']).iterrows():
        label = row.get('gvk_label')
        out[(row['well'], row['pack'], row['season'])] = {
            'depth': _depth(row), 'abs': _num(row.get('gvk_abs_m')), 'h_eff': _num(row.get('h_eff_m')),
            'label': '' if label is None or pd.isna(label) else str(label).strip(), 'date': row['date']}
    return out


def _pairs(labels: list[str], last_only: bool) -> list[tuple[str, list[str]]]:
    """Сезон и с какими прежними его сравнивают: с предыдущим в списке и с предыдущим однотипным (отбор с отбором).
    Первый сезон сравнивать не с чем. ``last_only`` — как в отчёте, только последние два сезона."""
    rows = []
    for i, label in enumerate(labels):
        if i == 0:
            continue
        targets = [labels[i - 1]]
        same = next((x for x in reversed(labels[:i - 1]) if split(x)[0] == split(label)[0]), None)
        if same:
            targets.insert(0, same)
        rows.append((label, targets))
    return rows[-2:] if last_only else rows


def _fmt(value: float) -> float | None:
    return None if math.isnan(value) else round(value, 2)


def comparison_table(number: int, pack: str, wells: list[str], labels: list[str], gvk: dict, span: str) -> Table:
    """5.5 / 5.7: глубина и а.о. ГВК по сезонам, в конце примечание (обводнена, нет замера)."""
    rows, columns = [], [Column('well', '№ скв.')]
    for i, label in enumerate(labels):
        columns += [Column(f's{i}_depth', 'глубина', 'м', 2, 'number'), Column(f's{i}_abs', 'а.о.', 'м', 2, 'number')]
    columns.append(Column('note', 'Примечание'))
    for well in wells:
        row: dict[str, Any] = {'well': well}
        notes = []
        for i, label in enumerate(labels):
            item = gvk.get((well, pack, label))
            row[f's{i}_depth'] = _fmt(item['depth']) if item else None
            row[f's{i}_abs'] = _fmt(item['abs']) if item else None
            if not item:
                notes.append(f'{name_of(label)}: нет замера')
            elif math.isnan(item['abs']) and item['label']:
                notes.append(f'{name_of(label)}: {item["label"]}')
        row['note'] = '; '.join(notes)
        rows.append(row)
    header = [[('', 1), *((name_of(label), 2) for label in labels), ('', 1)]]
    return Table(f'gis-an-5-{number}', f'Таблица 5.{number} – Сравнение положения ГВК пачки «{pack}» по результатам ГИС-контроль, '
                                       f'выполненных в {span}', pd.DataFrame(rows), columns, header=header,
                 note='Последний замер сезона по пачке. Пустая ячейка — нет замера или ГВК в сезоне; причина — в примечании.')


def change_table(number: int, pack: str, wells: list[str], labels: list[str], gvk: dict, last_only: bool) -> Table:
    """5.6 / 5.8: Δ глубины ГВК к предыдущему и к предыдущему однотипному сезону (плюс — ГВК опустился)."""
    rows, columns, header = [], [Column('well', '№ скв.')], [('', 1)]
    pairs = _pairs(labels, last_only)
    for label, targets in pairs:
        header.append((name_of(label), len(targets)))
        for old in targets:
            columns.append(Column(f'd_{label}_{old}', f'Δ с {name_of(old, "ins")}', 'м', 2, 'number'))
    for well in wells:
        row: dict[str, Any] = {'well': well}
        for label, targets in pairs:
            new = gvk.get((well, pack, label))
            for old_label in targets:
                old = gvk.get((well, pack, old_label))
                ok = new and old and not (math.isnan(new['abs']) or math.isnan(old['abs']))
                row[f'd_{label}_{old_label}'] = _fmt(old['abs'] - new['abs']) if ok else None
        rows.append(row)
    return Table(f'gis-an-5-{number}', f'Таблица 5.{number} – Относительное изменение положения ГВК пачки «{pack}» по результатам '
                                       'ГИС-контроля', pd.DataFrame(rows, columns=[c.key for c in columns]), columns, header=[header],
                 note='Δ — изменение глубины ГВК: плюс — ГВК опустился, минус — поднялся (= −Δ а.о.). Сравнение с предыдущим '
                      'сезоном и с предыдущим сезоном того же типа (отбор с отбором, закачка с закачкой).')


def results_table(intervals: pd.DataFrame, packs: pd.DataFrame, wells: list[str], pack_names: list[str], labels: list[str],
                  gvk: dict, span: str) -> Table:
    """5.4: по скважине и пачке строка на интервал; у каждого сезона интервалы, Кг %, Нг, ГВК глубина и а.о."""
    part = seasoned(intervals)
    part = part[part['season'].isin(labels) & part['well'].isin(wells) & part['pack'].isin(pack_names)]
    last = _last(part, ['well', 'pack', 'season'])[['well', 'pack', 'season', 'date']]
    part = part.merge(last, on=['well', 'pack', 'season', 'date'])
    columns = [Column('well', '№ скв.'), Column('pack', 'Пачка')]
    for i, label in enumerate(labels):
        columns += [Column(f's{i}_from', 'интервал от', 'м', 1, 'number'), Column(f's{i}_to', 'до', 'м', 1, 'number'),
                    Column(f's{i}_kg', 'Кг', '%', 1, 'number'), Column(f's{i}_h', 'Нг', 'м', 2, 'number'),
                    Column(f's{i}_depth', 'ГВК глубина', 'м', 2, 'number'), Column(f's{i}_abs', 'ГВК а.о.', 'м', 2, 'number')]
    rows = []
    for well in wells:
        for pack in pack_names:
            blocks = {}
            for label in labels:
                cut = part[(part['well'] == well) & (part['pack'] == pack) & (part['season'] == label)]
                blocks[label] = cut.sort_values('from_m', kind='stable').reset_index(drop=True)
            height = max([len(b) for b in blocks.values()] + [1])
            if not any(len(b) for b in blocks.values()) and not any((well, pack, s) in gvk for s in labels):
                continue
            for r in range(height):
                row: dict[str, Any] = {'well': well, 'pack': pack}
                for i, label in enumerate(labels):
                    b = blocks[label]
                    if r < len(b):
                        kg = _num(b.at[r, 'kg'])
                        row[f's{i}_from'], row[f's{i}_to'] = _fmt(_num(b.at[r, 'from_m'])), _fmt(_num(b.at[r, 'to_m']))
                        row[f's{i}_kg'] = None if math.isnan(kg) else round(kg * 100, 1)
                    item = gvk.get((well, pack, label))
                    if r == 0 and item:
                        row[f's{i}_h'], row[f's{i}_depth'], row[f's{i}_abs'] = (_fmt(item['h_eff']), _fmt(item['depth']), _fmt(item['abs']))
                rows.append(row)
    header = [[('', 2), *(('конец ' + name_of(label, 'gen'), 6) for label in labels)]]
    frame = pd.DataFrame(rows, columns=[c.key for c in columns])
    return Table(f'gis-an-5-{FIRST_NUMBER}', f'Таблица 5.{FIRST_NUMBER} – Результаты исследований ГИС-контроль, выполненных в {span}',
                 frame, columns, header=header, collapsed=True,
                 note='Интервалы последнего замера сезона по пачке; Кг — в процентах. Нг (hг эф) и ГВК — по пачке, в первой строке блока.')


def build(data: dict, params: dict[str, Any]) -> tuple[list[Table], list[str], str | None, list[str]]:
    """Таблицы 5.4–5.8, сезоны, новый сезон и заметки. ``data`` — {'packs': ..., 'intervals': ...}."""
    packs, intervals = data['packs'], data.get('intervals')
    notes: list[str] = []
    labels, base = pick(available(packs, intervals), params.get('an_base') or None, list(params.get('an_seasons') or []))
    if len(labels) < 1:
        return [], [], None, ['В базе ГИС нет замеров с определяемым сезоном (весна — март–май, осень — сентябрь–декабрь).']
    span = span_of(labels)
    ps = seasoned(packs)
    ps = ps[ps['season'].isin(labels)]
    wanted = [str(w) for w in params.get('an_wells') or []]
    wells = [w for w in order_names(ps['well'].unique()) if not wanted or w in wanted]
    pack_filter = [str(p) for p in params.get('packs') or []]
    pack_names = [p for p in order_names(ps['pack'].unique()) if not pack_filter or p in pack_filter]
    if not wells or not pack_names:
        return [], labels, base, ['За выбранные сезоны, скважины и пачки замеров нет.']
    gvk = gvk_by_season(packs, labels)
    tables: list[Table] = []
    if intervals is not None and len(intervals):
        tables.append(results_table(intervals, packs, wells, pack_names, labels, gvk, span))
    else:
        notes.append('Таблица 5.4 не построена: нет интервалов ГИС («База ГИС», таблица интервалов).')
    last_only = bool(params.get('an_last_two', True))
    number = FIRST_NUMBER + 1
    for pack in pack_names:
        has = sorted({w for (w, p, _s) in gvk if p == pack})
        shown = [w for w in wells if w in has]
        if not shown:
            continue
        tables.append(comparison_table(number, pack, shown, labels, gvk, span))
        tables.append(change_table(number + 1, pack, shown, labels, gvk, last_only))
        number += 2
    if number > 9:
        notes.append('Пачек больше двух: номера таблиц продолжены (5.9 и далее), в отчёте их нет.')
    return tables, labels, base, notes


def order_names(values) -> list[str]:
    from atlas.engine.core.config import ordered
    return ordered(str(v) for v in values)
