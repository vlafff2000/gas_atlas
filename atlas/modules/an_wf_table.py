"""Авторский надзор: табл. 1.6 — водный фактор (ВФ) по скважинам и сезонам отбора и график «скважины с водой + максимальный ВФ».

Вход — набор «Контроль воды» (замеры ВФ по скважинам помесячно: тот же, что читают «Карты» для обводнённости; его собирает
«БД замеров воды» из «Работы с исходными данными»). Структура таблицы как в отчёте АН: строка — скважина, колонка — сезон отбора.

Правила (подсказка программы; решает инженер — любую ячейку можно поменять вручную в таблице проверки):
- месяц замера относится к сезону отбора с наибольшим числом суток в этом месяце (как в «Картах»);
- несколько замеров ВФ скважины в сезоне — среднее по замерам с ВФ (как «Вод_фактор_сред» и тренд воды в «Картах»), по выбору — максимум
  (как «Вод_фактор_макс» и месячный график «Карт»);
- замер с ВФ > 0 — число; замер с ВФ = 0 — «сухо» (сухой газ без воды); замер без значения (КРС, ремонт, обводнение, нет расхода…)
  и сезон без суток с расходом газа — «простой»; сезон без замера при работе скважины — «–».
"""
from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from atlas.engine.core.config import ordered

from ..contract import Axis, Chart, Column, CellStyle, Data, Module, ModuleSpec, Note, Option, Param, ParamError, Result, Series, Stat, Table, TableAction
from ..domain import DatasetKind
from ._production import periods_of, visible_periods
from .an_report import well_scopes

PRODUCTION, WATER = DatasetKind.PRODUCTION, DatasetKind.WATER
OVERRIDES_KEY = 'wf_status'            # ручные ячейки в настройках проекта: «скважина|сезон» -> {'status': 'idle'|'dry'|'value', 'value': число}
OVERRIDES_JOURNAL = 'Таблица ВФ: ручные значения'
DRY, IDLE, NONE = 'сухо', 'простой', '–'
DRY_FILL, IDLE_FILL = 'CFE8D8', 'F6CFCF'          # пастельные зелёный и красный: те же в Excel и на экране
STATUS_TEXT = {'dry': DRY, 'idle': IDLE, 'none': NONE}
AGGS = (Option('mean', 'Среднее по замерам сезона (как в «Картах»)'), Option('max', 'Максимум по замерам сезона'))
WF_UNIT = 'л/1000 м³'
COLORS = {'bars': '#5B8DB8', 'line': '#C0504D'}
NOTE = ('Месяц замера относится к сезону отбора с наибольшим числом суток в месяце. Число — водный фактор, л/1000 м³ '
        '(несколько замеров за сезон — среднее по замерам с водой; в параметрах можно выбрать максимум); «сухо» — замеры без воды; '
        '«простой» — замер без значения (ремонт, КРС, обводнение и т.п.) или сезон без суток с расходом газа; «–» — скважина работала, замера нет. '
        'Это подсказка: значение любой ячейки можно задать вручную в таблице проверки ниже.')


def number_text(value: float) -> str:
    """Число как в отчёте: до одного знака, десятичная запятая, без хвостового нуля."""
    return f'{value:.1f}'.rstrip('0').rstrip('.').replace('.', ',') if np.isfinite(value) else ''


def season_spans(prod: pd.DataFrame, settings: Mapping[str, Any] | None) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    """Сезоны отбора из суточных данных: название -> (первые, последние сутки). Нейтральные периоды не берутся."""
    d = prod[prod.kind.eq('withdrawal')]
    out = {}
    for period in visible_periods(periods_of(d, 'withdrawal'), settings):
        dates = d.loc[d.period.eq(period), 'date']
        if dates.notna().any():
            out[period] = (dates.min().normalize(), dates.max().normalize())
    return out


def season_of_month(month: pd.Timestamp, spans: Mapping[str, tuple[pd.Timestamp, pd.Timestamp]]) -> str | None:
    """Сезон с наибольшим числом суток в месяце замера; при равенстве — более поздний. Вне сезонов — None."""
    first = month.to_period('M').to_timestamp()
    last = first + pd.offsets.MonthEnd(0)
    best, best_days, best_start = None, 0, None
    for name, (a, b) in spans.items():
        days = (min(b, last) - max(a, first)).days + 1
        if days > best_days or (days == best_days and days > 0 and a > best_start):
            best, best_days, best_start = name, days, a
    return best


def measurements(water: pd.DataFrame, spans: Mapping[str, tuple[pd.Timestamp, pd.Timestamp]]) -> pd.DataFrame:
    """Замеры ВФ: well, season, month, wf (NaN — значения нет), note. Повтор «скважина + месяц» — последний замер."""
    d = water.assign(well=water.well.astype(str), month=pd.to_datetime(water.date).dt.to_period('M').dt.to_timestamp(),
                     wf=pd.to_numeric(water.get('water_factor_l'), errors='coerce'),
                     note=water['comment'].fillna('').astype(str).str.strip() if 'comment' in water else '')
    d = d.sort_values('month', kind='stable').drop_duplicates(['well', 'month'], keep='last')
    d['note'] = d.note.where(~d.note.isin(['Ок', 'nan']), '')
    d['season'] = [season_of_month(m, spans) for m in d.month]
    return d[['well', 'season', 'month', 'wf', 'note']]


def classify(meas: pd.DataFrame, prod: pd.DataFrame | None, wells: list[str], seasons: list[str], agg: str) -> pd.DataFrame:
    """Автоматический разбор «скважина × сезон»: status (value/dry/idle/none), value, reason."""
    flow_days: dict[tuple[str, str], int] = {}
    rows_seen: set[tuple[str, str]] = set()
    month_flow: dict[tuple[str, pd.Timestamp], float] = {}
    if prod is not None and not prod.empty:
        d = prod[prod.kind.eq('withdrawal')].assign(well=lambda x: x.well.astype(str))
        flow_days = d[d.q.gt(0)].groupby(['well', 'period']).size().to_dict()
        rows_seen = set(zip(d.well, d.period))
        month_flow = d.assign(month=d.date.dt.to_period('M').dt.to_timestamp()).groupby(['well', 'month']).q.sum().to_dict()
    by_pair = {k: g for k, g in meas.groupby(['well', 'season'])}
    out = []
    for well in wells:
        for season in seasons:
            g = by_pair.get((well, season))
            status, value, reason = 'none', np.nan, 'нет замера в сезоне'
            if g is not None:
                wet = g.wf[g.wf.gt(0)]
                if not wet.empty:
                    status, value = 'value', float(wet.max() if agg == 'max' else wet.mean())
                    reason = f'замеров с водой: {len(wet)} из {len(g)}'
                else:
                    gaps, dry = g[g.wf.isna()], g[g.wf.notna()]
                    if dry.empty:
                        notes = [n for n in gaps.note if n]
                        status, reason = 'idle', '; '.join(dict.fromkeys(notes)) or 'замер без значения ВФ'
                    elif all((well, m) in month_flow and month_flow[(well, m)] <= 0 for m in dry.month):
                        status, reason = 'idle', 'нет расхода газа в месяце замера'
                    else:
                        status, reason = 'dry', 'замеры без воды'
            elif prod is not None:
                if flow_days.get((well, season), 0) > 0:
                    pass
                elif (well, season) in rows_seen:
                    status, reason = 'idle', 'нет суток с расходом газа в сезоне'
                else:
                    reason = 'нет данных за сезон'
            out.append({'well': well, 'season': season, 'status': status, 'value': value, 'reason': reason})
    return pd.DataFrame(out, columns=['well', 'season', 'status', 'value', 'reason'])


def parse_manual(text: Any) -> dict[str, Any] | None:
    """Ручное значение ячейки: «простой», «сухо» или число (ВФ); пусто — None (снять). Иначе ParamError."""
    s = str(text if text is not None else '').strip().lower().replace('ё', 'е')
    if not s:
        return None
    if s in ('простой', 'простаивает', 'idle'):
        return {'status': 'idle'}
    if s in ('сухо', 'нет воды', 'dry'):
        return {'status': 'dry'}
    try:
        number = float(s.replace(',', '.'))
    except ValueError:
        raise ParamError(f'«{text}»: допустимо «простой», «сухо», число (ВФ, л/1000 м³) или пусто (вернуть подсказку)') from None
    if not np.isfinite(number) or number <= 0:
        raise ParamError(f'«{text}»: ВФ должен быть положительным числом; нулевой ВФ — это «сухо»')
    return {'status': 'value', 'value': number}


def with_overrides(settings: Any, changes: Any) -> dict[str, Any]:
    """Настройки проекта с ручными ячейками таблицы ВФ. Пустое значение снимает правку."""
    if not isinstance(changes, Mapping) or not changes:
        raise ParamError('Нет изменений для сохранения')
    out = dict(settings)
    saved = {str(k): dict(v) for k, v in (out.get(OVERRIDES_KEY) or {}).items()}
    for key, value in changes.items():
        parsed = parse_manual(value.get('manual') if isinstance(value, Mapping) else value)
        if parsed is None:
            saved.pop(str(key), None)
        else:
            saved[str(key)] = parsed
    out[OVERRIDES_KEY] = saved
    return out


def apply_overrides(cells: pd.DataFrame, overrides: Mapping[str, Mapping[str, Any]]) -> pd.DataFrame:
    """Итог по ячейкам: подсказка программы, поверх — ручные значения. Колонки: key, manual (текст), final status/value."""
    cells = cells.assign(key=cells.well + '|' + cells.season, auto_status=cells.status, auto_value=cells.value, manual='')
    for i, key in enumerate(cells.key):
        o = overrides.get(key)
        if not o:
            continue
        cells.iat[i, cells.columns.get_loc('status')] = o.get('status', 'none')
        cells.iat[i, cells.columns.get_loc('value')] = float(o['value']) if o.get('status') == 'value' else np.nan
        cells.iat[i, cells.columns.get_loc('manual')] = number_text(float(o['value'])) if o.get('status') == 'value' else STATUS_TEXT[o['status']]
    return cells


def cell_text(status: str, value: float) -> str:
    return number_text(value) if status == 'value' else STATUS_TEXT.get(status, NONE)


def matrix_table(cells: pd.DataFrame, wells: list[str], seasons: list[str], title: str) -> Table:
    keys = [f's{i}' for i in range(len(seasons))]
    text = {(r.well, r.season): cell_text(r.status, r.value) for r in cells.itertuples()}
    frame = pd.DataFrame([{'well': w, **{k: text.get((w, s), NONE) for k, s in zip(keys, seasons)}} for w in wells])
    columns = [Column('well', '№ скв.'), *(Column(k, s) for k, s in zip(keys, seasons))]
    styles = []
    for status, fill in (('dry', DRY_FILL), ('idle', IDLE_FILL)):
        for col_key, season in zip(keys, seasons):
            rows = [i for i, w in enumerate(wells) if (w, season) in text and text[(w, season)] == STATUS_TEXT[status]]
            if rows:
                styles.append(CellStyle(rows=rows, fill=fill, columns=[col_key]))
    return Table('an-wf-table', title, frame, columns, note=NOTE, header=[[('', 1), (f'ВФ, {WF_UNIT}', len(seasons))]], styles=styles)


def check_table(cells: pd.DataFrame) -> Table:
    """Все ячейки с подсказкой и причиной; столбец «Вручную» правится — сохраняется в проекте и важнее подсказки."""
    def auto_text(r):
        return cell_text(r.auto_status, r.auto_value)
    frame = pd.DataFrame({'key': cells.key, 'well': cells.well, 'season': cells.season,
                          'auto': [auto_text(r) for r in cells.itertuples()], 'reason': cells.reason, 'manual': cells.manual,
                          'final': [cell_text(r.status, r.value) for r in cells.itertuples()]})
    columns = [Column('well', '№ скв.'), Column('season', 'Сезон'), Column('auto', 'Подсказка программы'), Column('reason', 'Причина'),
               Column('manual', 'Вручную'), Column('final', 'В таблице')]
    action = TableAction('assign', None, 'key', 'Сохранить ручные значения', target='wf-status', fields=('manual',), editable=('manual',),
                         journal=OVERRIDES_JOURNAL, submit='changed')
    return Table('an-wf-check', 'Проверка ячеек: подсказка, причина и ручное значение', frame, columns, action=action, collapsed=True,
                 note='Допустимо: «простой», «сухо» или число (ВФ). Пусто — вернуть подсказку программы. Итог решает инженер.')


def season_summary(cells: pd.DataFrame, seasons: list[str]) -> pd.DataFrame:
    rows = []
    for s in seasons:
        part = cells[cells.season.eq(s)]
        wet = part[part.status.eq('value')]
        top = wet.loc[wet.value.idxmax()] if not wet.empty else None
        rows.append({'season': s, 'wet': len(wet), 'wf_max': float(top.value) if top is not None else np.nan,
                     'wf_well': str(top.well) if top is not None else '', 'dry': int(part.status.eq('dry').sum()),
                     'idle': int(part.status.eq('idle').sum()), 'none': int(part.status.eq('none').sum())})
    return pd.DataFrame(rows)


def summary_table(summary: pd.DataFrame) -> Table:
    columns = [Column('season', 'Сезон'), Column('wet', 'Скважин с водой', decimals=0, kind='number'),
               Column('wf_max', f'Максимальный ВФ, {WF_UNIT}', decimals=1, kind='number'), Column('wf_well', 'Скважина с максимумом'),
               Column('dry', 'Сухо', decimals=0, kind='number'), Column('idle', 'Простой', decimals=0, kind='number'),
               Column('none', 'Нет замера', decimals=0, kind='number')]
    return Table('an-wf-summary', 'Итоги по сезонам', summary[[c.key for c in columns]], columns)


def wf_chart(summary: pd.DataFrame, group: str) -> Chart:
    cats = summary.season.tolist()
    chart = Chart('an-wf-chart', f'Скважины с водой в потоке и максимальный ВФ по сезонам{" · " + group if group else ""}',
                  Axis('Сезон', scale='category', categories=cats), Axis('Скважин с водой', 'шт', from_zero=True, step=1),
                  y2=Axis('Максимальный ВФ', WF_UNIT, from_zero=True))
    chart.series.append(Series('Скважин с водой', cats, summary.wet.to_numpy(float), 'bar', color=COLORS['bars']))
    chart.series.append(Series('Максимальный ВФ', cats, summary.wf_max.to_numpy(float), 'line', color=COLORS['line'], markers=True, width=2.2,
                               axis='y2', labels=[f'скв. {w}' if w else '' for w in summary.wf_well]))
    return chart


class WaterFactorTableModule(Module):
    spec = ModuleSpec(
        id='an_wf_table',
        title='Авторский надзор: ВФ по скважинам (табл. 1.6)',
        group='Авторский надзор',
        description='Водный фактор по скважинам и сезонам отбора: число, «сухо» (нет воды), «простой»; график скважин с водой и максимального ВФ.',
        needs=(WATER,),
        optional=(PRODUCTION,),
        order=116,
        save_label='Сохранить вид',
        params=(
            Param('groups', 'Группы', 'multi', default=[], dynamic=True, auto='first:1', section='Выбор данных',
                  help='Скважины групп (единое написание: «ГСП-9» = «ГСП 9»). Пусто — все скважины с замерами.'),
            Param('periods', 'Сезоны отбора', 'multi', default=[], dynamic=True, section='Выбор данных',
                  help='Колонки таблицы. Пусто — все сезоны отбора из суточных данных.'),
            Param('agg', 'Несколько замеров в сезоне', 'choice', default='mean', options=AGGS, section='Выбор данных',
                  formula='ВФ скважины за сезон = среднее (или максимум) по замерам сезона с ВФ > 0',
                  example='Замеры 10 и 20 л/1000 м³: среднее — 15, максимум — 20',
                  help='В «Картах» в сводках сезона считаются оба; тренд воды — по среднему.'),
        ),
    )

    def options(self, name: str, data: Data, params: dict[str, Any]) -> list[str]:
        prod = data[PRODUCTION] if PRODUCTION in data else None
        if name == 'groups':
            wells = ordered(set(data[WATER].well.astype(str)) | (set(prod.well.astype(str)) if prod is not None else set()))
            return ordered(set(well_scopes(data.mapping, wells).values()))
        if name == 'periods':
            return list(season_spans(prod, data.settings)) if prod is not None else []
        return super().options(name, data, params)

    def run(self, data: Data, params: dict[str, Any]) -> Result:
        result = Result()
        water = data[WATER]
        if 'water_factor_l' not in water or not pd.to_numeric(water.water_factor_l, errors='coerce').notna().any():
            result.notes.append(Note('В «Контроле воды» нет водного фактора: загрузите «БД замеров воды» (колонка «Водный фактор») заново.', 'warning'))
            return result
        prod = data[PRODUCTION] if PRODUCTION in data else None
        if prod is None or prod.empty:
            result.notes.append(Note('Нет «Отбора и закачки»: сезоны отбора неизвестны, таблица не построена.', 'warning'))
            return result
        spans = season_spans(prod, data.settings)
        meas = measurements(water, spans)
        outside = int(meas.season.isna().sum())
        meas = meas[meas.season.notna()]
        seasons = [s for s in spans if not params['periods'] or s in params['periods']]
        seasons = [s for s in seasons if s in set(meas.season)] if not params['periods'] else seasons
        wells = ordered(set(meas.well) | set(prod.well.astype(str)))
        scopes = well_scopes(data.mapping, wells)
        groups = set(params['groups'])
        measured = set(meas.well)
        wells = [w for w in wells if (scopes[w] in groups if groups else w in measured)]
        if not wells or not seasons:
            result.notes.append(Note('Нет замеров ВФ у выбранных групп в сезонах отбора.'))
            return result
        cells = classify(meas, prod, wells, seasons, params['agg'])
        cells = apply_overrides(cells, data.settings.get(OVERRIDES_KEY) or {})
        group = ', '.join(sorted(groups))
        summary = season_summary(cells, seasons)
        result.tables.append(matrix_table(cells, wells, seasons, f'ВФ по скважинам{" " + group if group else ""}, {seasons[0]} – {seasons[-1]}'))
        result.charts.append(wf_chart(summary, group))
        result.tables.append(summary_table(summary))
        result.tables.append(check_table(cells))
        manual = int(cells.manual.ne('').sum())
        result.summary = [Stat('Скважин', str(len(wells))), Stat('Сезонов', str(len(seasons))),
                          Stat('Вручную', str(manual), 'Ячейки, значение которых задал инженер; остальные — подсказка программы')]
        if outside:
            result.notes.append(Note(f'Замеров вне сезонов отбора (в таблицу не вошли): {outside}.'))
        return result
