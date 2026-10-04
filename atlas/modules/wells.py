"""Поскважинный анализ: сезоны эксплуатации, условия работы, продуктивность, вода, забой и конструкция.

Математика не переписана: суточный баланс, сезонные показатели, отдача при общем ΔP², наблюдения воды, выводы
и все графики — ``app.modules.well_analysis`` и ``app.modules.well_charts`` из 5.8 (фигуры Plotly переводятся
в ``Chart`` без пересчёта). Здесь выбор данных и представление. Полный перечень функций — docs/parity/wells.md.
"""
from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from app.core.config import ordered
from app.core.performance import select_wells
from app.modules import charts as legacy_charts
from app.modules import gdi as legacy_gdi
from app.modules import well_analysis as legacy
from app.modules import well_charts

from ..contract import (Axis, Chart, Column, Data, Module, ModuleSpec, Note, Option, Param, Result, Series, Table,
                        TableAction)
from ..domain import DatasetKind
from .gdi import GdiModule

K = DatasetKind
SECTION_DATA, SECTION_GDI_CMP, SECTION_VIEW, SECTION_GDI = 'Выбор данных', 'Сравнение ГДИ', 'Раздел', 'Индикаторные диаграммы'
SECTIONS = ('Эксплуатация', 'Продуктивность и ГДИ', 'Контроль воды', 'Забой и шаблонировка', 'Конструкция',
            'Выводы и качество')
OPERATING = ('daily', 'daily_mixed', 'shares', 'cumulative', 'cumulative_axis', 'seasonal', 'aligned', 'hours',
             'pressures', 'specific')
CHART_NAMES = {well_charts.LABELS[n]: n for n in OPERATING}
MAX_WELLS = 4                      # дашбордов за один расчёт: в 5.8 — одна скважина
RAW_MODULES = (K.PRODUCTION, K.OPERATIONS, K.WATER, K.BOTTOM, K.CONSTRUCTION)

# Подписи исходных колонок, как в ручном фильтре 5.8 (app/ui/point_tools.LABELS).
INPUT_LABELS = {'well': 'Скважина', 'date': 'Дата', 'kind': 'Тип', 'horizon': 'Горизонт', 'method': 'Метод',
                'study': 'Исследование', 'q': 'Q', 'dp2': 'ΔP²', 'level': 'Уровень, м', 'pressure': 'Рпл привед.',
                'file': 'Файл', 'sheet': 'Лист', '_row': 'Строка', 'work_hours': 'Часы работы',
                'gas_volume_m3': 'Объем газа, м³', 'water_volume_m3': 'Объем воды, м³',
                'water_rate': 'Расход воды, м³/сут', 'water_flag': 'Вода', 'bottom_m': 'Низ / забой, м',
                'top_m': 'Верх, м', 'tool_diameter_mm': 'Диаметр шаблона, мм', 'element': 'Элемент',
                'diameter_mm': 'Наружный диаметр, мм', 'inner_diameter_mm': 'Внутренний диаметр, мм',
                'comment': 'Комментарий'}
GDI_HISTORY_LABELS = {'date': 'Дата', 'method': 'Метод', 'study': 'Исследование', 'a': 'a', 'b': 'b', 'r2': 'R²',
                      'distinct_q': 'Разных Q', 'reliable': 'Достаточно данных', 'reference_dp2': 'Общий ΔP²',
                      'q_reference': 'Q при общем ΔP², тыс. м³/сут', 'q_free': 'Формальный Qсв', 'note': 'Примечание'}

VOLUME_NOTE = ('Объемы относятся к загруженным наблюдениям. Приоритет: явный суточный объем из эксплуатации, затем '
               'суточный расход из динамики × 1 день. Расход в часы работы = объем × 24 / известные часы. Пропуски не '
               'считаются нулем или простоем. Группы используются в текущем составе проекта.')
ALIGN_NOTE = ('По умолчанию первый фактический замер скважины каждого сезона расположен в нуле. Можно выбрать общую '
              'привязку к началу наблюдений объекта. Среднее за 7 дней строится при наличии минимум трех наблюдений; '
              'отсутствующие даты остаются пропусками.')
SPECIFIC_NOTE = ('Q/ΔP² — условный показатель для сопоставления режимов. Здесь Q рассчитан только для суток с '
                 'известными часами и объемом, давления относятся к тем же суткам. Он зависит от режима и не является '
                 'самостоятельным доказательством изменения проницаемости.')
GDI_NOTE = ('Используется прежняя модель ГДИ ΔP²=aQ+bQ². Достоверность сравнения зависит от одинаковых условий '
            'исследований и применимости модели. Qсв зависит также от пластового давления; выводы основаны на Q при '
            'общем ΔP².')
DP2_HELP = ('Автоматически выбирается середина общего измеренного диапазона надежных исследований одного метода. Вне '
            'диапазона или при отсутствии его пересечения сравнение не рассчитывается. Минимум три разных '
            'положительных Q и R² не ниже порога проекта.')
LEVEL_NOTE = ('Уровни относятся к указанным горизонтам этой скважины. Положительный уровень жидкости сам по себе не '
              'устанавливает обводненность добываемого газа.')
RAW_NOTE = ('Графики дашборда содержат производные показатели. Измерения можно исключить в таблицах ниже; анализ '
            'пересчитается. Щелчок по исходным точкам доступен также в основных разделах.')
FILTER_NOTE = 'Отметьте «Исключить» и примените изменения. Исходные значения сохраняются; снятый флажок восстанавливает точку.'


class WellsModule(Module):
    spec = ModuleSpec(
        id='wells',
        title='Поскважинный анализ',
        group='Скважины',
        description='Сезоны эксплуатации, условия работы, продуктивность, вода, забой и конструкция.',
        needs=(K.PRODUCTION,),
        optional=tuple(k for k in DatasetKind if k not in (K.PRODUCTION, K.PLAN)),
        order=70,
        save_label='Сохранить вид',
        params=(
            Param('groups', 'Группа анализа', 'multi', default=[], dynamic=True, section=SECTION_DATA),
            Param('wells', 'Скважина анализа', 'multi', default=[], dynamic=True, depends=('groups',), auto='first:1',
                  prefix='№ ', empty='ничего', section=SECTION_DATA,
                  help=f'Обычно одна скважина; можно сравнить до {MAX_WELLS} рядом.'),
            Param('kind', 'Режим эксплуатации', 'choice', default='withdrawal', section=SECTION_DATA,
                  options=(Option('withdrawal', 'Отбор'), Option('injection', 'Закачка'))),
            Param('periods', 'Периоды анализа', 'multi', default=[], dynamic=True, depends=('wells', 'kind'),
                  auto='last:3', section=SECTION_DATA),
            Param('methods', 'Метод ГДИ', 'multi', default=[], dynamic=True, depends=('wells',), section=SECTION_DATA,
                  help='Пусто — все методы.'),
            Param('threshold', 'Порог изменения для выводов', 'number', default=10.0, minimum=1, maximum=80, step=1,
                  unit='%', section=SECTION_DATA,
                  help='Изменение расхода или отдачи скважины между сезонами меньше порога считается «без изменений».',
                  formula='изменение = (значение сезона − значение предыдущего сезона) / значение предыдущего сезона × 100%',
                  example='Q при одинаковом ΔP² упал со 120 до 105 тыс. м³/сут: −12,5% — при пороге 10% это снижение.'),
            Param('asof', 'Дата состояния скважины', 'date', default=None, section=SECTION_DATA,
                  help='Эксплуатация и исследования ограничиваются этой датой. Для забоя, воды и конструкции '
                       'показывается последнее известное состояние на дату. Пусто — последняя дата данных проекта.'),
            Param('fixed_dp2', 'Задать общий ΔP² вручную', 'boolean', default=False, section=SECTION_GDI_CMP,
                  help=DP2_HELP),
            Param('dp2', 'Общий ΔP²', 'number', default=500.0, minimum=0.001, step=10, section=SECTION_GDI_CMP,
                  show_if={'fixed_dp2': True},
                  formula='Q(ΔP²) = (−a + √(a² + 4b·ΔP²)) / (2b)',
                  example='a = 0,7, b = 0,012, ΔP² = 500: Q = (−0,7 + √(0,49 + 24)) / 0,024 ≈ 177 тыс. м³/сут.'),
            Param('section', 'Раздел анализа', 'choice', default=SECTIONS[0], section=SECTION_VIEW,
                  options=tuple(Option(s, s) for s in SECTIONS)),
            Param('alignment', 'Начало отсчета сезонов', 'choice', default='well', section=SECTION_VIEW,
                  options=(Option('well', 'Первый замер скважины = 0'), Option('object', 'Первый день данных объекта')),
                  show_if={'section': 'Эксплуатация'}),
            # Значения — подписи графиков (список выбора показывает значения); имена 5.8 — CHART_NAMES.
            Param('charts', 'Графики эксплуатации', 'multi', default=[well_charts.LABELS['daily'],
                                                                       well_charts.LABELS['cumulative']],
                  empty='ничего', options=tuple(Option(well_charts.LABELS[n], well_charts.LABELS[n]) for n in OPERATING),
                  section=SECTION_VIEW,
                  show_if={'section': 'Эксплуатация'}),
            Param('gdi_n', 'Последние даты ГДИ', 'choice', default=0, section=SECTION_GDI,
                  options=(Option(0, 'Все'), Option(1, '1'), Option(2, '2'), Option(3, '3')),
                  show_if={'section': 'Продуктивность и ГДИ'}),
            Param('gdi_orientation', 'Оси ГДИ', 'choice', default='standard', section=SECTION_GDI,
                  options=(Option('standard', 'X = Q, Y = ΔP²'), Option('swapped', 'X = ΔP², Y = Q')),
                  show_if={'section': 'Продуктивность и ГДИ'}),
            Param('gdi_curves', 'Расчетные кривые ГДИ', 'boolean', default=True, section=SECTION_GDI,
                  show_if={'section': 'Продуктивность и ГДИ'}),
            Param('gdi_db', 'Кривые по коэффициентам БД', 'boolean', default=True, section=SECTION_GDI,
                  show_if={'section': 'Продуктивность и ГДИ'}),
            Param('gdi_crosshair', 'Перекрестная линейка ГДИ', 'boolean', default=True, section=SECTION_GDI,
                  show_if={'section': 'Продуктивность и ГДИ'}),
            Param('gdi_excluded', 'Показывать исключенные точки ГДИ', 'boolean', default=True, section=SECTION_GDI,
                  show_if={'section': 'Продуктивность и ГДИ'}),
            Param('gdi_seasons', 'Сезоны ГДИ', 'multi', default=[], dynamic=True, depends=('wells', 'methods'),
                  section=SECTION_GDI, show_if={'section': 'Продуктивность и ГДИ'}),
            Param('raw', 'Показать исходные данные и ручной фильтр', 'boolean', default=False, section=SECTION_VIEW),
        ),
    )

    # --- варианты зависимых списков ---
    def options(self, name: str, data: Data, params: dict[str, Any]) -> list[str]:
        if name == 'groups':
            return ordered(group_of(data.mapping, w) for w in all_wells(data))
        if name == 'wells':
            groups = set(params.get('groups') or [])
            return [w for w in all_wells(data) if not groups or group_of(data.mapping, w) in groups]
        wells = list(params.get('wells') or [])
        if name == 'periods':
            return periods_of(data, wells, params.get('kind') or 'withdrawal')
        if name == 'methods':
            return ordered(select_wells(data[K.GDI], wells).method) if K.GDI in data and wells else []
        if name == 'gdi_seasons':
            if K.GDI not in data.raw or not wells:
                return []
            d = legacy_gdi.prepare(select_wells(data.raw[K.GDI], wells))
            if params.get('methods'):
                d = d[d.method.isin(params['methods'])]
            return ordered(d.season[d.season.ne('')])
        return super().options(name, data, params)

    # --- расчёт ---
    def run(self, data: Data, params: dict[str, Any]) -> Result:
        result = Result()
        everyone = all_wells(data)
        if not everyone:
            result.notes.append(Note('Загрузите данные скважин через «Импорт данных» (пока — в версии 5.8).', 'warning'))
            return result
        wells = [w for w in params['wells'] if w in set(everyone)]
        if not wells:
            result.notes.append(Note('Выберите скважину анализа.', 'warning'))
            return result
        if len(wells) > MAX_WELLS:
            result.notes.append(Note(f'Показаны первые {MAX_WELLS} из {len(wells)} выбранных скважин. '
                                     'Поскважинный анализ рассчитан на одну скважину; уберите лишние из списка.',
                                     'warning'))
            wells = wells[:MAX_WELLS]
        missing = [title for kind, title in ((K.OPERATIONS, 'суточные часы и вода'), (K.WATER, 'контроль воды'),
                                             (K.BOTTOM, 'замеры забоя'), (K.CONSTRUCTION, 'конструкция'))
                   if kind not in data]
        if missing:
            result.notes.append(Note('Для полного анализа не загружены: ' + ', '.join(missing) +
                                     '. Шаблоны доступны в «Импорт данных».'))
        for well in wells:
            self.dashboard(result, data, params, well, prefix=len(wells) > 1)
        result.notes.append(Note(VOLUME_NOTE))
        return result

    def dashboard(self, result: Result, data: Data, params: dict[str, Any], well: str, prefix: bool) -> None:
        analysis, selection = analyze(data, params, well)
        settings = view_settings(data.settings, params)
        head = f'Скважина №{well} · ' if prefix else ''
        key = f'{well}'
        daily, stats = analysis['daily'], analysis['seasons']

        # Карточки 5.8 — одна таблица «Показатель / значение».
        rows = [{'Показатель': label, 'Значение': fmt(value, precision), 'Пояснение': hint or ''}
                for label, value, precision, hint in legacy.metrics(analysis)]
        result.tables.append(Table(f'metrics-{key}', head + 'Скважина №' + well + ' · ' + group_of(data.mapping, well),
                                   pd.DataFrame(rows)))
        gasdays = int(daily.gas_volume_m3.notna().sum()) if not daily.empty else 0
        knownhours = int(daily.work_hours.notna().sum()) if not daily.empty else 0
        result.notes.append(Note(f'{head}Данные газа: {gasdays} суток; часы известны: {knownhours} суток. Дата состояния: '
                                 f'{pd.Timestamp(selection["asof"]).strftime("%d.%m.%Y")}.'))
        available = well_charts.available(analysis)

        def plot(name: str):
            if name in available:
                result.charts.append(chart_of(analysis, name, settings, f'wells-{key}-{name}', data))

        section = params['section']
        if section == 'Эксплуатация':
            if daily.empty:
                result.notes.append(Note(head + 'Нет суточных данных для выбранного режима и периодов.', 'warning'))
            else:
                wanted = {CHART_NAMES[label] for label in params['charts']}
                for name in [n for n in OPERATING if n in wanted]:
                    plot(name)
                absent = [well_charts.LABELS[n] for n in OPERATING if n in wanted and n not in available]
                if absent:
                    result.notes.append(Note(head + 'Нет данных для графиков: ' + '; '.join(absent) + '.'))
                result.notes.append(Note(ALIGN_NOTE))
                if 'specific' in available and 'specific' in wanted:
                    result.notes.append(Note(SPECIFIC_NOTE))
            result.tables.append(Table(f'seasons-{key}', head + 'Сезонные показатели',
                                       stats.rename(columns=legacy.SEASON_LABELS).reset_index(drop=True),
                                       collapsed=True))
        elif section == 'Продуктивность и ГДИ':
            if analysis['gdi'].empty:
                result.notes.append(Note(head + 'Нет ГДИ в выбранном диапазоне периодов.', 'warning'))
            else:
                plot('gdi')
                plot('gdi_history')
                history = analysis['gdi_history']
                result.tables.append(Table(f'gdi-{key}', head + 'Отдача при одинаковом ΔP²',
                                           history[list(GDI_HISTORY_LABELS)].rename(columns=GDI_HISTORY_LABELS),
                                           note=GDI_NOTE))
                controls = analysis['gdi_raw']
                if params['gdi_seasons'] and not controls.empty:
                    controls = controls[legacy_gdi.prepare(controls).season.isin(params['gdi_seasons'])]
                controls = legacy_gdi.select_studies(controls, [well], int(params['gdi_n']))
                if not controls.empty and '_point_id' in controls:
                    table = GdiModule.point_table(controls, data.excluded)
                    table.id, table.title = f'gdi-points-{key}', head + 'Ручной фильтр точек ГДИ · поскважинный анализ'
                    result.tables.append(table)
        elif section == 'Контроль воды':
            plot('water')
            plot('water_log')
            if analysis['water'].empty:
                result.notes.append(Note(head + 'Наличие воды неизвестно: загрузите контроль воды или суточный объем воды.'))
            else:
                result.tables.append(Table(f'water-{key}', head + 'Наблюдения воды', analysis['water'].reset_index(drop=True)))
            if not daily.empty and daily.water_factor.notna().any():
                factor = daily[['date', 'gas_volume_m3', 'water_volume_m3', 'water_factor']].rename(columns={
                    'date': 'Дата', 'gas_volume_m3': 'Газ, м³', 'water_volume_m3': 'Вода, м³',
                    'water_factor': 'Вода, м³ / млн м³ газа'})
                result.tables.append(Table(f'water-factor-{key}', head + 'Водогазовый фактор', factor.reset_index(drop=True)))
            if K.RESPONSE in data:
                r = select_wells(data[K.RESPONSE], [well])
                r = r[r.level.notna()] if 'level' in r else r.iloc[0:0]
                if not r.empty:
                    fig = legacy_charts.response_chart(r, data.settings.get('working_horizons', []), 'level')
                    result.charts.append(figure_chart(fig, f'wells-{key}-levels'))
                    result.notes.append(Note(LEVEL_NOTE))
        elif section == 'Забой и шаблонировка':
            plot('bottom')
            if analysis['bottom'].empty:
                result.notes.append(Note(head + 'Загрузите даты и измеренные глубины забоя. Диаметр шаблона, метод и '
                                         'комментарий можно указать дополнительно.'))
            else:
                result.tables.append(Table(f'bottom-{key}', head + 'Замеры забоя', inputs(analysis['bottom'])))
        elif section == 'Конструкция':
            plot('construction')
            construction = analysis['construction']
            if construction.empty:
                result.notes.append(Note(head + 'Нет снимка конструкции на выбранную дату. Одна строка шаблона — один '
                                         'элемент или интервал; все элементы снимка имеют одну дату.'))
            else:
                result.notes.append(Note(head + 'Снимок от ' + construction.date.max().strftime('%d.%m.%Y') +
                                         '. Глубины привязаны к единому нулю, указанному в вашей документации. Элементы '
                                         'с неизвестным диаметром показаны условной шириной.'))
                result.tables.append(Table(f'construction-{key}', head + 'Конструкция', inputs(construction)))
        else:
            result.tables.append(Table(f'signals-{key}', head + 'Выводы и основания',
                                       analysis['signals'].reset_index(drop=True)))
        if params['raw']:
            result.notes.append(Note(RAW_NOTE))
            for kind in RAW_MODULES:
                if kind in data.raw:
                    table = raw_table(data, kind, well, head)
                    if table is not None:
                        result.tables.append(table)

    # --- сохранённый вид: формат 5.8 (как viewer['well_dashboard'] — его читает «Экспорт» 5.8) ---
    def panel_key(self, panel: int = 0) -> str:
        return 'well_dashboard'

    def save_state(self, params: dict[str, Any], data: Data) -> dict[str, Any]:
        methods = params['methods']
        return {
            'wells': list(params['wells']), 'kind': params['kind'], 'periods': list(params['periods']),
            'delta': float(params['dp2']) if params['fixed_dp2'] else None, 'threshold': float(params['threshold']),
            'method': methods[0] if len(methods) == 1 else None, 'asof': params['asof'] or str(default_asof(data).date()),
            'alignment': params['alignment'],
            'gdi': {'n': int(params['gdi_n']), 'orientation': params['gdi_orientation'], 'curves': params['gdi_curves'],
                    'db_curves': params['gdi_db'], 'crosshair': params['gdi_crosshair'],
                    'show_excluded': params['gdi_excluded'], 'seasons': list(params['gdi_seasons'])},
            # Только для 6: в 5.8 эти поля держит сессия, «Экспорт» 5.8 их не использует.
            '_atlas6': {'groups': list(params['groups']), 'methods': list(methods), 'section': params['section'],
                        'charts': [CHART_NAMES[c] for c in params['charts']], 'raw': params['raw'], 'asof_fixed': bool(params['asof'])},
        }

    def load_state(self, state: Mapping[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name in ('wells', 'kind', 'periods', 'threshold', 'alignment'):
            if state.get(name) is not None:
                out[name] = state[name]
        if state.get('delta') is not None:
            out.update(fixed_dp2=True, dp2=float(state['delta']))
        if state.get('method') is not None:
            out['methods'] = [state['method']]
        gdi = state.get('gdi') or {}
        for old, new in (('n', 'gdi_n'), ('orientation', 'gdi_orientation'), ('curves', 'gdi_curves'),
                         ('db_curves', 'gdi_db'), ('crosshair', 'gdi_crosshair'), ('show_excluded', 'gdi_excluded'),
                         ('seasons', 'gdi_seasons')):
            if gdi.get(old) is not None:
                out[new] = gdi[old]
        extra = state.get('_atlas6') or {}
        for name in ('groups', 'methods', 'section', 'raw'):
            if extra.get(name) is not None:
                out[name] = extra[name]
        if extra.get('charts') is not None:
            out['charts'] = [well_charts.LABELS[n] for n in extra['charts'] if n in OPERATING]
        if extra.get('asof_fixed') and state.get('asof'):
            out['asof'] = str(state['asof'])[:10]
        return out


# ---------- выбор данных ----------

def group_of(mapping: Mapping[str, Mapping[str, str]], well: str) -> str:
    return mapping.get(well, {}).get('group', 'Без группы')


def all_wells(data: Data) -> list[str]:
    """Все скважины проекта, как ``catalog['wells']`` 5.8: по всем наборам с колонкой well."""
    found: set = set()
    for frame in data.raw.values():
        if 'well' in frame:
            found.update(frame.well.dropna().astype(str).unique())
    return ordered(found)


def frames_of(data: Data) -> dict[str, pd.DataFrame]:
    return {k.value: data[k] for k in data}


def periods_of(data: Data, wells: list[str], kind: str) -> list[str]:
    """Как в 5.8: периоды выбранной скважины и режима по дате окончания."""
    if not wells:
        return []
    daily = legacy.dataset(frames_of(data), data.settings, data.mapping)['daily']
    if daily.empty:
        return []
    chosen = daily[daily.well.isin(wells) & daily.kind.eq(kind)]
    return [str(p) for p in chosen.groupby('period').date.max().sort_values().index.tolist()]


def default_asof(data: Data) -> pd.Timestamp:
    """Как в 5.8: последняя дата среди всех загруженных наборов (``catalog['modules'][*]['end']``)."""
    ends = [pd.to_datetime(f.date).max() for f in data.raw.values() if 'date' in f and not f.empty]
    ends = [e for e in ends if pd.notna(e)]
    return max(ends) if ends else pd.Timestamp.today().normalize()


def analyze(data: Data, params: Mapping[str, Any], well: str) -> tuple[dict, dict]:
    """``well_analysis.analyze`` с теми же аргументами, что строит страница 5.8, плюс исходные ГДИ (``gdi_raw``)."""
    frames = frames_of(data)
    kind = params['kind']
    available = periods_of(data, [well], kind)
    chosen = [p for p in params['periods'] if p in available] if params['periods'] else available
    methods = list(params['methods'])
    method = methods[0] if len(methods) == 1 else None
    if len(methods) > 1 and 'gdi' in frames:
        gdi = frames['gdi']
        frames['gdi'] = gdi[gdi.method.fillna('').astype(str).isin(methods)]
    asof = pd.Timestamp(params['asof']).date() if params['asof'] else default_asof(data).date()
    delta = float(params['dp2']) if params['fixed_dp2'] else None
    analysis = dict(legacy.analyze(frames, data.settings, data.mapping, well, kind, chosen if available else None,
                                   delta, float(params['threshold']), method, asof))
    # Исходные точки ГДИ (для серых исключённых и ручного фильтра) — тот же отбор, что в 5.8.
    raw = data.raw.get(K.GDI)
    original = select_wells(raw, [well]) if raw is not None else pd.DataFrame()
    if not original.empty:
        original = original[original.date.le(pd.Timestamp(asof))]
        if methods:
            original = original[original.method.fillna('').astype(str).isin(methods)]
        if chosen and not analysis['daily'].empty:
            mask = pd.Series(False, index=original.index)
            for _, g in analysis['daily'].groupby('period'):
                mask |= original.date.between(g.date.min(), g.date.max())
            original = original[mask]
    analysis['gdi_raw'] = original
    return analysis, {'periods': chosen, 'asof': asof, 'method': method, 'delta': delta}


def view_settings(settings: Mapping[str, Any], params: Mapping[str, Any]) -> dict[str, Any]:
    """Параметры графиков, как ``dashboard_settings`` страницы 5.8."""
    return {**settings, 'dashboard_alignment': params['alignment'],
            'dashboard_gdi': {'n': int(params['gdi_n']), 'orientation': params['gdi_orientation'],
                              'curves': params['gdi_curves'], 'db_curves': params['gdi_db'],
                              'crosshair': params['gdi_crosshair'], 'show_excluded': params['gdi_excluded'],
                              'seasons': list(params['gdi_seasons'])}}


# ---------- представление ----------

def fmt(value, precision) -> str:
    """Как ``well_dashboard.number`` 5.8: пробел между разрядами, «Нет данных» вместо пропуска."""
    if precision is None:
        return str(value)
    return f'{float(value):,.{precision}f}'.replace(',', ' ') if pd.notna(value) and np.isfinite(value) else 'Нет данных'


def inputs(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.drop(columns=['_point_id'], errors='ignore').rename(columns=INPUT_LABELS).reset_index(drop=True)


def raw_table(data: Data, kind: DatasetKind, well: str, head: str) -> Table | None:
    """Ручной фильтр исходных измерений скважины (как ``point_controls.tools`` 5.8)."""
    source = select_wells(data.raw[kind], [well])
    if source.empty or '_point_id' not in source:
        return None
    order = [c for c in ('date', 'well') if c in source]
    source = source.sort_values(order, ascending=[False, True][:len(order)]).reset_index(drop=True)
    source = source.assign(_excluded=source['_point_id'].isin(data.excluded),
                           _reason=source['_point_id'].map(lambda i: (data.excluded.get(i) or {}).get('reason', '')))
    columns = []
    for c in INPUT_LABELS:
        if c in source:
            label = INPUT_LABELS[c]
            if c == 'q':
                label = 'Q, м³/сут' if kind == K.PRODUCTION else 'Q, тыс. м³/сут'
            numeric = pd.api.types.is_numeric_dtype(source[c]) and not pd.api.types.is_bool_dtype(source[c])
            columns.append(Column(c, label, kind='date' if c == 'date' else 'number' if numeric else 'text'))
    columns.append(Column('_reason', 'Причина исключения'))
    return Table(f'raw-{kind.value}-{well}', f'{head}Ручной фильтр · {kind.label} · №{well}', source, columns,
                 note=FILTER_NOTE, collapsed=True,
                 action=TableAction('exclude', kind, '_point_id', 'Применить ручной фильтр', checked_column='_excluded'))


def chart_of(analysis: dict, name: str, settings: Mapping[str, Any], cid: str, data: Data) -> Chart:
    if name == 'gdi':
        return gdi_chart(analysis, settings, cid)
    return figure_chart(well_charts.build(analysis, name, dict(settings)), cid)


def gdi_chart(a: dict, settings: Mapping[str, Any], cid: str) -> Chart:
    """Индикаторные диаграммы — построитель раздела ГДИ 6 (порт ``charts.gdi_chart``) на выборке ``well_charts.build``:
    точки можно исключать щелчком, как в разделе ГДИ."""
    cfg = settings.get('dashboard_gdi', {})
    well = a['well']
    selected = legacy_gdi.select_studies(a['gdi'], [well], cfg.get('n', 0), cfg.get('seasons'))
    original = legacy_gdi.select_studies(a.get('gdi_raw', a['gdi']), [well], cfg.get('n', 0), cfg.get('seasons'))
    studies = legacy_gdi.analyze(selected, settings.get('r2_threshold', .95))
    params = {'orientation': cfg.get('orientation', 'standard'), 'curves': cfg.get('curves', True),
              'db_curves': cfg.get('db_curves', True), 'crosshair': cfg.get('crosshair', True),
              'show_excluded': cfg.get('show_excluded', True)}
    chart = GdiModule.chart(selected, studies, original, well, params)
    chart.id, chart.title = cid, 'Скважина №' + well + ' · ГДИ'
    return chart


def _values(values) -> list:
    if values is None:
        return []
    return list(values.tolist() if hasattr(values, 'tolist') and not isinstance(values, pd.DatetimeIndex) else values)


def _axis(layout_axis, values: list, fallback: str = '') -> Axis:
    title = (layout_axis.title.text if layout_axis is not None and layout_axis.title is not None else None) or fallback
    scale = 'value'
    categories = None
    if layout_axis is not None and layout_axis.type == 'date':
        scale = 'time'
    elif values and all(isinstance(v, str) for v in values if v is not None):
        scale = 'category'
        categories = list(dict.fromkeys(str(v) for v in values if v is not None))
    inverse = layout_axis is not None and layout_axis.autorange == 'reversed'
    from_zero = layout_axis is not None and layout_axis.rangemode == 'tozero'
    return Axis(title, scale=scale, inverse=bool(inverse), from_zero=bool(from_zero), categories=categories)


def figure_chart(fig, cid: str) -> Chart:
    """Фигура Plotly 5.8 → ``Chart`` без пересчёта: те же точки, подписи, цвета, оси и вторая шкала справа."""
    layout = fig.layout
    xs = [v for t in fig.data for v in _values(t.x)]
    y1 = [v for t in fig.data if (t.yaxis or 'y') == 'y' for v in _values(t.y)]
    y2 = [v for t in fig.data if t.yaxis == 'y2' for v in _values(t.y)]
    chart = Chart(cid, (layout.title.text or '') if layout.title is not None else '', _axis(layout.xaxis, xs),
                  _axis(layout.yaxis, y1))
    if any(t.yaxis == 'y2' for t in fig.data):
        chart.y2 = _axis(layout.yaxis2, y2)
    for t in fig.data:
        axis = 'y2' if t.yaxis == 'y2' else 'y'
        group = t.legendgroup or ''
        legend = t.showlegend is not False
        x, y = _values(t.x), _values(t.y)
        if chart.x.scale == 'category':
            x = [None if v is None else str(v) for v in x]
        if t.type == 'bar':
            color = t.marker.color if isinstance(t.marker.color, str) else ''
            chart.series.append(Series(t.name or '', x, y, 'bar', group=group, legend=legend, color=color, axis=axis))
            continue
        mode = t.mode or 'lines'
        line_color = t.line.color if isinstance(t.line.color, str) else ''
        marker_color = t.marker.color if isinstance(t.marker.color, str) else ''
        hollow = marker_color in ('white', '#fff', '#ffffff')
        color = line_color or ('' if hollow else marker_color)
        if 'lines' in mode:
            dash = t.line.dash if t.line.dash in ('solid', 'dash', 'dot', 'dashdot', 'longdash') else ''
            chart.series.append(Series(t.name or '', x, y, 'line', group=group, legend=legend, color=color,
                                       dash=dash, width=float(t.line.width or 0), markers='markers' in mode,
                                       hollow=hollow, axis=axis))
        else:
            chart.series.append(Series(t.name or '', x, y, 'points', group=group, legend=legend, color=color,
                                       hollow=hollow, axis=axis))
    return chart
