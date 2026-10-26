"""Спад пластового давления в конце сезонов закачки: наложение сезонов, суточная закачка, хвост сезона, таблица и связь темпа со спадом.

Для любого объекта и группы проекта: данные — суточная закачка (как в «Сезонных показателях») и давление объекта
(столбец «Давление объекта», иначе опорная сетка). Границы сезона, дата максимума и окно последнего месяца берутся автоматически
и показываются с основанием в таблице; параметр «Вручную» (JSON по сезонам) их заменяет — последнее слово за инженером.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ..contract import Axis, Chart, Column, Data, Module, ModuleSpec, Note, Option, Param, ParamError, Result, Series, Stat, Table
from ..domain import DatasetKind
from . import _seasonal as S
from ._production import PRODUCTION
from .an_report import object_pressure_of, pressure_near

P_UNIT = 'кгс/см²'
Q_UNIT = 'тыс. м³/сут'
SECTION_DATA, SECTION_CALC, SECTION_VIEW, SECTION_MANUAL = 'Выбор данных', 'Расчёт', 'Вид', 'Вручную'
END_WINDOW_DAYS = 3        # максимум в последние дни сезона — подсказка «проверьте границу»
AFTER_END_DAYS = 4         # давление на конец закачки: замер в первые 4 суток после её окончания
NOTE = ('Сезоны закачки; объём и темп — по суткам с расходом, как в «Сезонных показателях». Давление — абсолютное. '
        'Подсказки: границы сезона — из проекта («Настройки → Расписание периодов» или автоопределение); максимум — наибольший '
        'замер внутри сезона; давление на конец закачки — замер на ближайшую дату после её окончания (1–4 сут), иначе ближайший '
        'замер в пределах 30 суток. Всё это можно поправить в параметре «Вручную».')
MANUAL_HELP = ('JSON по сезонам, ключ — название сезона: {"2023": {"start": "2023-04-01", "end": "2023-10-18", '
               '"max_date": "2023-10-12", "last_from": "2023-09-19", "fit": false}}. Можно задать любые поля; остальное — '
               'автоматически. "fit": false — не брать сезон в связь «давление — темп».')
HOLD_COLUMNS = [Column('period', 'Сезон'), Column('pmax', 'Максимум давления', P_UNIT, 1, 'number'),
                Column('mean_season', 'Фактический темп сезона', Q_UNIT, 1, 'number'),
                Column('last_mean', 'Фактический темп последнего месяца', Q_UNIT, 1, 'number'),
                Column('rate_req', 'Темп, нужный для удержания максимума', Q_UNIT, 1, 'number'),
                Column('gap_last', 'Нужный темп минус темп последнего месяца', Q_UNIT, 1, 'number'),
                Column('in_fit', 'В связи «давление — темп»')]
COLUMNS = [Column('period', 'Сезон'), Column('start', 'Начало', kind='date'), Column('end', 'Конец', kind='date'),
           Column('max_date', 'Дата максимума', kind='date'), Column('pmax', 'Максимум давления', P_UNIT, 1, 'number'),
           Column('p_end', 'Давление на конец закачки', P_UNIT, 1, 'number'),
           Column('fall', 'Спад от максимума', P_UNIT, 1, 'number'),
           Column('since_max', 'Суток от максимума до конца', kind='number'),
           Column('volume', 'Объём сезона', 'млн м³', 2, 'number'),
           Column('last_volume', 'Закачка за последний месяц', 'млн м³', 2, 'number'),
           Column('last_mean', 'Темп последнего месяца', Q_UNIT, 1, 'number'),
           Column('last_share', 'Темп последнего месяца к среднему за сезон', '%', 1, 'number'),
           Column('basis', 'Основание границ и подсказок')]


def _manual_for(manual: dict[str, Any] | None, period: str) -> dict[str, Any]:
    entry = (manual or {}).get(period) or {}
    if not isinstance(entry, dict):
        raise ParamError(f'«Вручную»: сезон {period} задан не объектом')
    return entry


def _date(entry: dict[str, Any], key: str, period: str, fallback: pd.Timestamp | None) -> pd.Timestamp | None:
    if not entry.get(key):
        return fallback
    try:
        return pd.Timestamp(entry[key]).normalize()
    except (TypeError, ValueError):
        raise ParamError(f'«Вручную»: сезон {period}, поле «{key}»: дата не распознана') from None


def _season(df: pd.DataFrame, row: Any, pressure: pd.DataFrame | None, last_days: int, manual: dict[str, Any] | None) -> dict[str, Any]:
    """Один сезон закачки: суточный ряд, давление, максимум, конец закачки, окно последнего месяца и основания подсказок."""
    entry = _manual_for(manual, row.period)
    start = _date(entry, 'start', row.period, row.start)
    end = _date(entry, 'end', row.period, row.end)
    daily = S._daily(df[df.kind.eq('injection') & df.period.eq(row.period)])
    daily = daily[(daily.index >= start) & (daily.index <= end)]
    flow = daily[daily > 0]
    # Максимум — только внутри сезона; на графики идут и замеры в первые сутки после окончания закачки.
    shown = pressure[pressure.date.between(start, end + pd.Timedelta(days=AFTER_END_DAYS))].dropna(subset=['pressure']) \
        if pressure is not None else None
    press = shown[shown.date <= end] if shown is not None else None
    basis = []
    basis.append('граница: вручную' if entry.get('start') or entry.get('end') else 'граница: проект')
    if press is not None and not press.empty:
        if entry.get('max_date'):
            max_date = _date(entry, 'max_date', row.period, None)
            pmax = pressure_near(pressure, max_date)
            basis.append('максимум: вручную')
        else:
            top = press.loc[press.pressure.idxmax()]
            max_date, pmax = top.date, float(top.pressure)
            basis.append('максимум: наибольший замер в сезоне')
            if (end - max_date).days <= END_WINDOW_DAYS:
                basis.append('максимум у конца сезона: проверьте, не обрезана ли закачка')
    else:
        max_date, pmax = None, None
    p_end, end_basis = _pressure_at_end(pressure, end)
    basis.append(end_basis)
    last_from = _date(entry, 'last_from', row.period, end - pd.Timedelta(days=last_days - 1))
    if entry.get('last_from'):
        basis.append('окно последнего месяца: вручную')
    last = flow[(flow.index >= last_from) & (flow.index <= end)]
    mean_season = float(flow.mean()) / 1e3 if len(flow) else np.nan
    mean_last = float(last.mean()) / 1e3 if len(last) else np.nan
    return {
        'period': row.period, 'start': start, 'end': end, 'max_date': max_date, 'pmax': pmax, 'p_end': p_end,
        'fall': (pmax - p_end) if pmax is not None and p_end is not None else np.nan,
        'since_max': (end - max_date).days if max_date is not None else np.nan,
        'volume': float(flow.sum()) / 1e6, 'last_volume': float(last.sum()) / 1e6, 'last_mean': mean_last,
        'last_share': mean_last / mean_season * 100.0 if mean_season else np.nan, 'mean_season': mean_season,
        'basis': '; '.join(basis), 'daily': daily, 'press': press, 'shown': shown, 'last_from': last_from,
        'in_fit': entry.get('fit', True) is not False,
    }


def _pressure_at_end(pressure: pd.DataFrame | None, end: pd.Timestamp) -> tuple[float | None, str]:
    """Давление на конец закачки: замер на ближайшую дату после её окончания (до AFTER_END_DAYS суток), иначе ближайший в пределах 30 сут."""
    if pressure is None or pressure.empty:
        return None, 'давления нет'
    valid = pressure.dropna(subset=['pressure'])
    after = valid[valid.date.between(end, end + pd.Timedelta(days=AFTER_END_DAYS))].sort_values('date')
    if not after.empty:
        top = after.iloc[0]
        return float(top.pressure), f'давление на конец: замер {top.date:%d.%m.%Y}, через {(top.date - end).days} сут после конца'
    value = pressure_near(pressure, end)
    if value is None:
        return None, f'давления на конец нет: замеров в {AFTER_END_DAYS} сут после конца нет, в пределах 30 сут тоже'
    return value, f'давление на конец: замеров в {AFTER_END_DAYS} сут после конца нет, взят ближайший в пределах 30 сут'


def _hold_fit(rows: list[dict[str, Any]]) -> dict[str, float] | None:
    """Линейная связь максимума давления с средним темпом сезона: pmax = intercept + slope × темп. None — данных мало или темп не менялся."""
    pts = [r for r in rows if r['in_fit'] and not pd.isna(r['pmax']) and not pd.isna(r['mean_season'])]
    if len(pts) < 2:
        return None
    x = np.array([r['mean_season'] for r in pts], float)
    y = np.array([r['pmax'] for r in pts], float)
    if np.ptp(x) == 0:
        return None
    slope, intercept = np.polyfit(x, y, 1)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - float(((y - (intercept + slope * x)) ** 2).sum()) / ss_tot if ss_tot else np.nan
    return {'slope': float(slope), 'intercept': float(intercept), 'r2': r2, 'n': len(pts), 'x_min': float(x.min()), 'x_max': float(x.max())}


class InjectionDeclineModule(Module):
    spec = ModuleSpec(
        id='injection-decline',
        title='Спад давления в конце закачки',
        group='Эксплуатация',
        description='Конец сезонов закачки: давление достигает максимума и падает из-за снижения темпов в последний месяц. '
                    'Наложение сезонов, хвост закачки, таблица и связь темпа со спадом.',
        needs=(PRODUCTION,),
        optional=(DatasetKind.OBJECT_PRESSURE, DatasetKind.PRESSURE_MATCH, DatasetKind.RESPONSE, DatasetKind.GAS_DB),
        order=13,
        params=(
            Param('seasons', 'Последних сезонов закачки', 'integer', default=5, minimum=1, maximum=20, section=SECTION_DATA,
                  help='Берутся последние по времени сезоны закачки; если выбраны сезоны ниже — этот параметр не действует'),
            Param('periods', 'Сезоны', 'multi', default=[], dynamic=True, empty='последние по числу выше', section=SECTION_DATA),
            Param('source', 'Давление', 'choice', default='auto', section=SECTION_DATA, options=(
                Option('auto', 'Автоматически: столбец из БД, иначе опорная сетка'), Option('object', 'Столбец «Давление объекта»'),
                Option('grid', 'Опорная сетка: реагирование'), Option('match', 'Опорная сетка: кроссплот, факт')),
                help='Давление объекта: столбец из БД или опорная сетка (среднее по группам на дату)'),
            Param('last_days', 'Окно последнего месяца, сут', 'integer', default=30, minimum=7, maximum=92, section=SECTION_CALC,
                  help='Последние дни сезона: за них считаются закачка и темп. Сдвинуть для отдельного сезона — «Вручную» (last_from)'),
            Param('tail_days', 'Хвост сезона на графике, сут', 'integer', default=45, minimum=14, maximum=120, section=SECTION_CALC),
            Param('x_mode', 'Ось X на наложении', 'choice', default='start', section=SECTION_VIEW, options=(
                Option('start', 'От начала закачки'), Option('end', 'До конца закачки (0 = конец)')),
                help='От начала — конец каждого сезона отмечен пунктиром в цвете кривой. До конца — сезоны совпадают по концу закачки'),
            Param('manual', 'Поправки по сезонам', 'json', default=None, section=SECTION_MANUAL, help=MANUAL_HELP),
        ),
    )

    def options(self, name: str, data: Data, params: dict[str, Any]) -> list[str]:
        if name == 'periods':
            return S.season_table(data[PRODUCTION], data[DatasetKind.GAS_DB] if DatasetKind.GAS_DB in data else None) \
                .query('kind == "injection"').period.tolist()
        return super().options(name, data, params)

    def run(self, data: Data, params: dict[str, Any]) -> Result:
        result = Result()
        df = data[PRODUCTION]
        ref = data[DatasetKind.GAS_DB] if DatasetKind.GAS_DB in data else None
        seasons = S.season_table(df, ref, S.SOURCE_AUTO)
        seasons = seasons[seasons.kind.eq('injection')].sort_values('start')
        if params.get('periods'):
            seasons = seasons[seasons.period.isin(params['periods'])]
        else:
            seasons = seasons.tail(int(params.get('seasons') or 5))
        if seasons.empty:
            result.notes.append(Note('Нет сезонов закачки с расходом по выбранным условиям.', 'warning'))
            return result
        pressure, _, label = object_pressure_of(data, params.get('source') or 'auto')
        if pressure is None or pressure.empty:
            result.notes.append(Note('Нет давления объекта: загрузите «Давление объекта» или опорную сетку '
                                     '(«Реагирование», «Кроссплот давлений»). Графики и таблица по давлению пусты.', 'warning'))
        else:
            result.notes.append(Note(f'Давление: {label}.'))
        result.notes.append(Note(NOTE))
        rows = [_season(df, r, pressure, int(params.get('last_days') or 30), params.get('manual'))
                for r in seasons.itertuples()]
        fit = _hold_fit(rows)
        for r in rows:
            usable = fit is not None and fit['slope'] > 0 and not pd.isna(r['pmax'])
            r['rate_req'] = (r['pmax'] - fit['intercept']) / fit['slope'] if usable else np.nan
            r['gap_last'] = r['rate_req'] - r['last_mean']
        if fit is None:
            result.notes.append(Note('Темп, нужный для удержания максимума, не рассчитан: нужно не меньше двух сезонов с давлением '
                                     'и разным средним темпом закачки.', 'warning'))
        elif fit['slope'] <= 0:
            result.notes.append(Note('Темп, нужный для удержания максимума, не рассчитан: по сезонам связь давления с темпом '
                                     'не положительная — выше темп не дал более высокого максимума.', 'warning'))
        result.summary = self.summary(rows) + self.fit_summary(fit)
        result.charts += self.charts(rows, int(params.get('tail_days') or 45), pressure is not None, params.get('x_mode') or 'start')
        result.tables.append(self.table(rows))
        if fit is not None and fit['slope'] > 0:
            result.charts.append(self.hold_chart(rows, fit))
            result.tables.append(self.hold_table(rows))
        for r in rows:
            if 'проверьте' in r['basis']:
                result.notes.append(Note(f'Сезон {r["period"]}: {r["basis"]}.', 'warning'))
        return result

    @staticmethod
    def summary(rows: list[dict[str, Any]]) -> list[Stat]:
        drops = [r['fall'] for r in rows if not pd.isna(r['fall'])]
        shares = [r['last_share'] for r in rows if not pd.isna(r['last_share'])]
        out = [Stat('Сезонов закачки', str(len(rows)))]
        if drops:
            out.append(Stat('Средний спад от максимума', f'{np.mean(drops):.1f} {P_UNIT}', f'по {len(drops)} сезонам с давлением'))
        if shares:
            out.append(Stat('Темп последнего месяца', f'{np.mean(shares):.0f} % от среднего', 'среднее по сезонам'))
        return out

    @staticmethod
    def fit_summary(fit: dict[str, float] | None) -> list[Stat]:
        if fit is None or fit['slope'] <= 0:
            return []
        return [Stat('Связь давления и темпа', f'+{fit["slope"]:.2f} {P_UNIT} на 1 {Q_UNIT}',
                     f'по {fit["n"]} сезонам, R² = {fit["r2"]:.2f}; оценка по малой выборке')]

    @staticmethod
    def hold_chart(rows: list[dict[str, Any]], fit: dict[str, float]) -> Chart:
        """Максимум давления против среднего темпа сезона и прямая связи: по ней читается темп, нужный для удержания максимума."""
        pts = [r for r in rows if r['in_fit'] and not pd.isna(r['pmax']) and not pd.isna(r['mean_season'])]
        chart = Chart('decline-hold', 'Максимум давления и темп закачки, нужный для его удержания',
                      Axis('Средний темп закачки сезона', Q_UNIT, from_zero=True), Axis('Максимум давления', P_UNIT))
        xs = [fit['x_min'], fit['x_max']]
        chart.series.append(Series('Связь давления и темпа', xs, [fit['intercept'] + fit['slope'] * x for x in xs], 'line',
                                   group='fit', dashed=True, labels=['прямая связи', 'прямая связи']))
        chart.series.append(Series('Сезоны', [r['mean_season'] for r in pts], [r['pmax'] for r in pts], 'points', group='seasons',
                                   labels=[f'сезон {r["period"]}: темп {r["mean_season"]:.0f}, максимум {r["pmax"]:.1f}' for r in pts]))
        return chart

    @staticmethod
    def hold_table(rows: list[dict[str, Any]]) -> Table:
        frame = pd.DataFrame(rows)[[c.key for c in HOLD_COLUMNS]].assign(
            in_fit=lambda f: f.in_fit.map({True: 'да', False: 'нет'}))
        return Table('decline-hold-rate', 'Темп закачки, нужный для удержания максимума давления', frame, HOLD_COLUMNS,
                     note='Прямая: максимум давления = a + b × средний темп сезона (по сезонам с отметкой «да»). Нужный темп = '
                          '(максимум − a) / b: сколько нужно закачивать, чтобы давление держалось на уровне своего максимума. '
                          'Отрицательная разница — темп последнего месяца уже выше нужного. Выборка мала: оценка ориентировочная; '
                          'исключить сезон можно параметром «Вручную» (fit: false).')

    @staticmethod
    def charts(rows: list[dict[str, Any]], tail_days: int, has_pressure: bool, x_mode: str = 'start') -> list[Chart]:
        out: list[Chart] = []
        if has_pressure:
            by_end = x_mode == 'end'
            overlay = Chart('decline-overlay', 'Давление в сезонах закачки: наложение ' + ('по дням до конца закачки' if by_end else 'по дням с начала'),
                            Axis('Дней до конца закачки (0 = конец)' if by_end else 'Сутки с начала закачки', 'сут', from_zero=not by_end),
                            Axis('Давление', P_UNIT))
            shown = [r for r in rows if r['shown'] is not None and not r['shown'].empty]
            lo = min((float(r['shown'].pressure.min()) for r in shown), default=0.0)
            hi = max((float(r['shown'].pressure.max()) for r in shown), default=0.0)
            for r in shown:
                origin = r['end'] if by_end else r['start']
                x = (r['shown'].date - origin).dt.days.to_numpy(float)
                overlay.series.append(Series(f'сезон {r["period"]}', x, r['shown'].pressure.to_numpy(float), 'line', group=r['period'],
                                             markers=True, labels=[d.strftime('%d.%m.%Y') for d in r['shown'].date]))
                if not by_end:   # конец закачки каждого сезона — пунктирная вертикаль в цвете кривой
                    end_x = float((r['end'] - r['start']).days)
                    overlay.series.append(Series(f'конец {r["period"]}', [end_x, end_x], [lo, hi], 'line', group=r['period'], dashed=True,
                                                 legend=False, labels=[f'Конец закачки {r["end"]:%d.%m.%Y}'] * 2))
                if not pd.isna(r['p_end']):   # давление на конец закачки — квадрат на оси конца
                    overlay.series.append(Series(f'на конец {r["period"]}', [float((r['end'] - origin).days)], [r['p_end']], 'points',
                                                 group=r['period'], symbol='square', legend=False,
                                                 labels=[f'Давление на конец закачки {r["end"]:%d.%m.%Y}: {r["p_end"]:.1f}']))
                if r['max_date'] is not None:
                    overlay.series.append(Series(f'максимум {r["period"]}', [float((r['max_date'] - origin).days)], [r['pmax']], 'points',
                                                 group=r['period'], symbol='diamond', legend=False,
                                                 labels=[f'Максимум {r["max_date"]:%d.%m.%Y}: {r["pmax"]:.1f}']))
            out.append(overlay)
        rate = Chart('decline-rate', 'Суточная закачка по сезонам', Axis('Сутки с начала закачки', 'сут', from_zero=True),
                     Axis('Закачка', Q_UNIT, from_zero=True))
        for r in rows:
            d = r['daily']
            if d.empty:
                continue
            rate.series.append(Series(f'сезон {r["period"]}', (d.index - r['start']).days.to_numpy(float), d.to_numpy(float) / 1e3,
                                      'line', group=r['period'], labels=[t.strftime('%d.%m.%Y') for t in d.index]))
        out.append(rate)
        tail = Chart('decline-tail', f'Последние {tail_days} сут закачки: давление и темп', Axis('Дней до конца закачки', 'сут'),
                     Axis('Давление', P_UNIT), y2=Axis('Закачка', Q_UNIT, from_zero=True))
        for r in rows:
            if has_pressure and r['shown'] is not None and not r['shown'].empty:
                p = r['shown'][r['shown'].date >= r['end'] - pd.Timedelta(days=tail_days - 1)]
                if len(p):
                    tail.series.append(Series(f'сезон {r["period"]}', (p.date - r['end']).dt.days.to_numpy(float),
                                              p.pressure.to_numpy(float), 'line', group=r['period'], markers=True,
                                              labels=[d.strftime('%d.%m.%Y') for d in p.date]))
            d = r['daily'][r['daily'].index >= r['end'] - pd.Timedelta(days=tail_days - 1)]
            if len(d):
                tail.series.append(Series(f'закачка {r["period"]}', (d.index - r['end']).days.to_numpy(float), d.to_numpy(float) / 1e3,
                                          'line', group=r['period'], dashed=True, axis='y2', legend=False,
                                          labels=[t.strftime('%d.%m.%Y') for t in d.index]))
        out.append(tail)
        pts = [r for r in rows if not pd.isna(r['fall']) and not pd.isna(r['last_mean'])]
        if pts:
            scatter = Chart('decline-scatter', 'Темп закачки в последний месяц и спад давления',
                            Axis('Средний темп последнего месяца', Q_UNIT, from_zero=True),
                            Axis('Спад давления от максимума', P_UNIT, from_zero=True))
            scatter.series.append(Series('Сезоны', [r['last_mean'] for r in pts], [r['fall'] for r in pts], 'points', group='Сезоны',
                                         labels=[f'сезон {r["period"]}: темп {r["last_mean"]:.0f}, спад {r["fall"]:.1f}' for r in pts]))
            out.append(scatter)
        return out

    @staticmethod
    def table(rows: list[dict[str, Any]]) -> Table:
        frame = pd.DataFrame(rows)[[c.key for c in COLUMNS]]
        return Table('decline-seasons', 'Спад давления по сезонам закачки', frame, COLUMNS,
                     note='Спад — максимум минус давление на конец закачки. Темп последнего месяца — средний расход по суткам с расходом '
                          'в окне; «к среднему за сезон» — тот же показатель по всему сезону. Основание в последнем столбце показывает, '
                          'что взято автоматически, а что задано в «Вручную».')
