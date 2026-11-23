"""Графики и таблицы дашборда «Паспорта скважины» в общем контракте (``atlas.contract``).

Экран рисует их тем же ``ChartView`` и ``TableView``, что и остальные модули, а выгрузка PNG/XLSX идёт тем же кодом ``render``.
Здесь только выбор данных из карточки (``passport_card.build``) и представление; расчётов нет.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .contract import Axis, Chart, CellStyle, Column, HeatMap, Series, Table

KIND_LABEL = {'withdrawal': 'Отбор', 'injection': 'Закачка'}


def _f(values: list[Any]) -> np.ndarray:
    return np.array([np.nan if v is None else v for v in values], float)


def seasons_chart(seasons: list[dict[str, Any]]) -> Chart | None:
    """Объём по сезонам парами: сезон отбора и следующий за ним сезон закачки (отбор 2025-2026 + закачка 2026) — одна категория.

    Пары определяет общий разбор модуля «Сезонные показатели» (``passport_card.assign_pairs``), слева направо по времени."""
    from atlas.modules import _seasonal as S
    rows = [r for r in reversed(seasons) if r['volume'] is not None and r.get('cycle') is not None]      # таблица идёт от свежего сезона
    if not rows:
        return None
    frame = pd.DataFrame({'kind': [r['kind'] for r in rows], 'cycle': [r['cycle'] for r in rows], 'period': [r['period'] for r in rows],
                          'volume': _f([r['volume'] for r in rows]), 'days': [r['days'] for r in rows],
                          'max_rate': _f([r['max_rate'] for r in rows])})
    cycles = sorted(frame.cycle.unique())
    names = {c: S.cycle_label(c) for c in cycles}
    cats = [names[c] for c in cycles]
    chart = Chart('passport-seasons', 'Объём по сезонам: отбор и следующая за ним закачка', Axis('Пара (отбор + закачка)', scale='category', categories=cats),
                  Axis('Объём', 'млн м³', from_zero=True))
    for kind, label in KIND_LABEL.items():
        part = frame[frame.kind.eq(kind)].drop_duplicates('cycle', keep='last').set_index('cycle')
        if part.empty:
            continue
        have = [c for c in cycles if c in part.index]
        chart.series.append(Series(label, [names[c] for c in have], part.loc[have, 'volume'].to_numpy(float), 'bar', group=label,
                                   labels=[f"{label}, сезон {part.at[c, 'period']} · Qmax {part.at[c, 'max_rate']:.1f} тыс. м³/сут"
                                           if pd.notna(part.at[c, 'max_rate']) else f"{label}, сезон {part.at[c, 'period']}" for c in have]))
    return chart


def daily_chart(daily: dict[str, dict[str, list]], cru: tuple[list[str], list[float | None]] | None = None) -> Chart | None:
    """Суточные расходы за все сезоны: отбор и закачка линиями по времени; в подсказке часы работы."""
    chart = Chart('passport-daily', 'Суточные расходы', Axis('Дата', scale='time'), Axis('Суточный объём', 'тыс. м³/сут', from_zero=True),
                  crosshair=True)
    for kind, label in KIND_LABEL.items():
        s = daily.get(kind) or {}
        if not s.get('date'):
            continue
        hours = [f'Часы работы: {h:g}' if h is not None else 'Часы работы: нет данных' for h in s['hours']]
        chart.series.append(Series(label, pd.to_datetime(s['date']).to_numpy(), _f(s['volume']), 'line', group=label, labels=hours,
                                   width=1.4))
    if chart.series and cru and cru[0]:
        # КРУ — на правой оси, как в «Производительности» (общий ряд ЭЛПРО, свой цвет и шкала); включается легендой
        from atlas.modules import _elpro_series as E
        chart.y2 = E.extra_axis('cru')
        chart.series.append(Series(E.LABEL['cru'], pd.to_datetime(cru[0]).to_numpy(), _f(cru[1]), 'line', axis='y2', color=E.COLOR['cru'], width=1.2,
                                   group=E.LABEL['cru']))
    return chart if chart.series else None


def gdi_chart(items: list[dict[str, Any]]) -> Chart | None:
    """Индикаторные диаграммы: точки режимов (q, Δp²) и кривая Δp² = a·q + b·q² каждого исследования; ненадёжные — пунктиром."""
    if not items:
        return None
    chart = Chart('passport-gdi', 'Индикаторные диаграммы ГДИ', Axis('Дебит q', 'тыс. м³/сут', from_zero=True),
                  Axis('Δp² = p<sub>пл</sub>² − p<sub>заб</sub>²', '(кгс/см²)²', from_zero=True))
    for g in items:
        by_coef = g.get('by_coef', False)
        name = g['date'] + (' · ' + g['method'] if g['method'] else '') + (' (по коэффициентам)' if by_coef else '' if g['reliable'] else ' (ненадёжное)')
        qs = [p[0] for p in g['points']] or [q for o in items for q in (p[0] for p in o['points'])]
        if by_coef:
            if g['a'] is not None and g['b'] is not None and qs:
                curve = np.linspace(0, max(qs) * 1.05, 41)
                chart.series.append(Series(name, curve, g['a'] * curve + g['b'] * curve ** 2, 'line', group=name, dash='dashdot',
                                           tooltip='По коэффициентам интерпретатора, без замеров давлений'))
            continue
        chart.series.append(Series(name, qs, [p[1] for p in g['points']], 'points', group=name,
                                   tooltip='' if g['reliable'] else 'Ненадёжное исследование: решает инженер'))
        if g['a'] is not None and g['b'] is not None:
            top = max(qs) * 1.05
            curve = np.linspace(0, top, 41)
            chart.series.append(Series(name + ' (аппроксимация)', curve, g['a'] * curve + g['b'] * curve ** 2, 'line', group=name,
                                       dashed=not g['reliable'], legend=False))
    return chart


def seasons_table(seasons: list[dict[str, Any]]) -> Table | None:
    if not seasons:
        return None
    frame = pd.DataFrame({
        'kind': [KIND_LABEL[r['kind']] for r in seasons], 'period': [r['period'] for r in seasons],
        'volume': _f([r['volume'] for r in seasons]), 'days': [r['days'] for r in seasons],
        'max_rate': _f([r['max_rate'] for r in seasons]), 'max_date': [r['max_date'] for r in seasons],
        'mean_rate': _f([r['mean_rate'] for r in seasons]), 'hours': _f([r['hours'] for r in seasons]),
        'water': _f([r['water'] for r in seasons])})
    return Table('passport-seasons', 'Сезоны эксплуатации', frame, [
        Column('kind', 'Вид'), Column('period', 'Сезон'), Column('volume', 'Объём', 'млн м³', 2, 'number'),
        Column('days', 'Отработано дней', '', 0, 'number'), Column('max_rate', 'Qmax', 'тыс. м³/сут', 1, 'number'),
        Column('max_date', 'Дата Qmax'), Column('mean_rate', 'Qср', 'тыс. м³/сут', 1, 'number'),
        Column('hours', 'Часы', '', 0, 'number'), Column('water', 'Вода', 'м³', 1, 'number')],
        note='Сверху самый свежий сезон, затем предыдущий другого вида (отбор / закачка) и так далее.')


def gdi_table(rows: list[dict[str, Any]]) -> Table | None:
    if not rows:
        return None
    frame = pd.DataFrame({
        'date': [r['date'] for r in rows], 'method': [r['method'] or '—' for r in rows],
        'a': _f([r['a'] for r in rows]), 'b': _f([r['b'] for r in rows]), 'r2': _f([r['r2'] for r in rows]),
        'q_max': _f([r['q_max'] for r in rows]), 'q_free': _f([r['q_free'] for r in rows]),
        'reliable': ['да' if r['reliable'] else 'нет' for r in rows],
        'by_coef': ['да' if r.get('by_coef') else '' for r in rows]})
    bad = [i for i, r in enumerate(rows) if not r['reliable']]
    return Table('passport-gdi', 'ГДИ за всё время', frame, [
        Column('date', 'Дата'), Column('method', 'Метод'), Column('a', 'a', '', 3, 'number'), Column('b', 'b', '', 4, 'number'),
        Column('r2', 'R²', '', 3, 'number'), Column('q_max', 'Qmax', '', 0, 'number'), Column('q_free', 'Qсв', '', 0, 'number'),
        Column('reliable', 'Надёжно'), Column('by_coef', 'По коэфф. (без замеров)')], styles=[CellStyle(bad, font='808080')] if bad else [],
        note='Ненадёжные исследования выделены серым, но не скрыты: решает инженер.')


def krs_table(krs: dict[str, Any]) -> Table | None:
    if not krs['works']:
        return None
    frame = pd.DataFrame({'year': [w['year'] if w['year'] is not None else np.nan for w in krs['works']],
                          'type': [w['type'] for w in krs['works']], 'detail': [w['detail'] for w in krs['works']]})
    return Table('passport-krs', 'Проведённые КРС', frame, [
        Column('year', 'Год', '', 0, 'number'), Column('type', 'Тип ремонта'), Column('detail', 'Подробности')])


def _tile(chart_id: str, title: str, tile: dict[str, Any] | None, texts: list[str], scale: str, missing: str, unit: str) -> Chart | None:
    """Плитка по годам — общая тепловая карта из одной строки; цвет задаёт шкала (её можно сменить в оформлении, как у любой карты)."""
    if not tile:
        return None
    cols = tile['columns']
    chart = Chart(chart_id, title, Axis('Сезон', scale='category', categories=cols), Axis('', scale='category', categories=[title]),
                  style={'heat_scale': scale, 'heat_bar': 'hide'})
    chart.heat = HeatMap([title], cols, [[None if v is None else float(v) for v in tile['cells']]], [texts], unit, 1.0, missing)
    return chart


def tile_charts(tiles: dict[str, Any] | None) -> list[Chart]:
    """Плитки КРУ и КРС по годам: закрашены годы с песком в ревизии КРУ и годы ремонтов."""
    tiles = tiles or {}
    kru, krs = tiles.get('kru'), tiles.get('krs')
    out = [_tile('passport-kru-tiles', 'Ревизия КРУ', kru, ['песок' if v else '' if v == 0 else 'нет ревизии' for v in kru['cells']] if kru else [],
                 'redgreen', 'нет ревизии', 'песок'),
           _tile('passport-krs-tiles', 'КРС', krs, krs['texts'] if krs else [], 'orange', 'нет данных', 'ремонт')]
    return [c for c in out if c]


def elpro_table(rows: list[dict[str, Any]]) -> Table | None:
    """Сезоны отбора по ЭЛПРО: открытие КРУ, расход на 1 % КРУ, давление при обычном расходе и вывод-подсказка."""
    if not rows:
        return None
    frame = pd.DataFrame({k: ([r[k] for r in rows] if k in ('period', 'verdict', 'reason') else _f([r[k] for r in rows]))
                          for k in ('period', 'days', 'mean_open', 'max_open', 'high_share', 'eff', 'eff_change', 'p_same_q', 'p_change', 'verdict', 'reason')})
    bad = [i for i, r in enumerate(rows) if r['verdict'] == 'внимание']
    return Table('passport-elpro', 'ЭЛПРО по сезонам отбора', frame, [
        Column('period', 'Сезон'), Column('days', 'Суток ЭЛПРО', '', 0, 'number'), Column('mean_open', 'КРУ средн.', '%', 1, 'number'),
        Column('max_open', 'КРУ макс.', '%', 0, 'number'), Column('high_share', 'Суток КРУ ≥ 90 %', '%', 0, 'number'),
        Column('eff', 'Расход на 1 % КРУ', 'тыс. м³/сут', 2, 'number'), Column('eff_change', 'Изменение к прошлому сезону', '%', 0, 'number'),
        Column('p_same_q', 'Давление при обычном расходе', 'кгс/см²', 1, 'number'), Column('p_change', 'Изменение давления', 'кгс/см²', 1, 'number'),
        Column('verdict', 'Вывод'), Column('reason', 'Причина')], styles=[CellStyle(bad, font='b45f06')] if bad else [],
        note='Вывод — подсказка с причиной; пороги фиксированы (КРУ ≥ 90 % в 30 % суток; падение расхода на 1 % КРУ на 15 %). Решает инженер.')


def assess_table(rows: list[dict[str, Any]]) -> Table | None:
    """Оценка состояния: механизм, уровень (авто или решение инженера), причина, дата данных и подсказка операции."""
    if not rows:
        return None
    from atlas.passport_assess import LEVEL_NAMES
    frame = pd.DataFrame({'name': [r['name'] for r in rows], 'level': [LEVEL_NAMES[r['level']] for r in rows],
                          'who': [('решение инженера' + (f': {r["note"]}' if r['note'] else '')) if r['manual'] else 'авто' for r in rows],
                          'reason': [r['reason'] for r in rows], 'date': [r['date'] for r in rows], 'recommendation': [r['recommendation'] for r in rows]})
    manual = [i for i, r in enumerate(rows) if r['manual']]
    return Table('passport-assess', 'Оценка состояния скважины', frame, [
        Column('name', 'Механизм'), Column('level', 'Улика'), Column('who', 'Кто решил'), Column('reason', 'Причина'), Column('date', 'Данные от'),
        Column('recommendation', 'Что делать (подсказка)')], styles=[CellStyle(manual, font='1f4e8c')] if manual else [],
        note='Это подсказка: решает инженер. Замер до последнего КР и старше двух лет в оценку не идёт; пропуск данных — «неизвестно», не «хорошо».')


def backtest_tables(result: dict[str, Any]) -> list[Table]:
    """Проверка критериев на истории: итог по годам и по механизмам (общая таблица ядра)."""
    def pct(v):
        return '' if v is None else f'{v * 100:.0f} %'
    def num(v):
        return '' if v is None else f'{v:.1f}'
    years, mechs = result.get('years') or [], result.get('mechanisms') or []
    out = []
    if years:
        frame = pd.DataFrame({'year': [str(y['year']) for y in years], 'wells': [y['wells'] for y in years], 'repaired': [y['repaired'] for y in years],
                              'hits': [y['hits'] for y in years], 'precision': [pct(y['precision']) for y in years], 'lift': [num(y['lift']) for y in years],
                              'flagged': [y['flagged'] for y in years], 'flagged_hits': [y['flagged_hits'] for y in years], 'missing': [y['missing'] for y in years]})
        out.append(Table('passport-backtest-years', 'Проверка критериев на истории: по годам', frame, [
            Column('year', 'Год КР'), Column('wells', 'Скважин с данными до 1 января'), Column('repaired', 'Ушли в КР в этом году (K)'),
            Column('hits', 'Из них в верхних K по сумме улик'), Column('precision', 'Точность в верхних K'), Column('lift', 'Во сколько раз лучше случайного'),
            Column('flagged', 'Скважин хоть с одной уликой'), Column('flagged_hits', 'Из них ушли в КР'), Column('missing', 'КР скважин без данных до даты')],
            note=' '.join(result.get('notes') or []) + ' Верхние K: берём столько скважин с наибольшей суммой улик, сколько ушло в КР; «лучше случайного» = 1 значит, улики не помогают.'))
    if mechs:
        frame = pd.DataFrame({'name': [m['name'] for m in mechs], 'a': [f"{m['repaired_hit']} из {m['repaired']}" for m in mechs],
                              'sa': [pct(m['share_repaired']) for m in mechs], 'b': [f"{m['other_hit']} из {m['other']}" for m in mechs],
                              'sb': [pct(m['share_other']) for m in mechs], 'lift': [num(m['lift']) for m in mechs],
                              'ssa': [pct(m.get('strong_repaired')) for m in mechs], 'ssb': [pct(m.get('strong_other')) for m in mechs],
                              'slift': [num(m.get('strong_lift')) for m in mechs]})
        out.append(Table('passport-backtest-mechanisms', 'Проверка критериев на истории: по механизмам', frame, [
            Column('name', 'Механизм'), Column('a', 'Улика у ушедших в КР (скважино-лет)'), Column('sa', 'Доля'), Column('b', 'Улика у остальных (скважино-лет)'),
            Column('sb', 'Доля'), Column('lift', 'Во сколько раз чаще у ушедших в КР'), Column('ssa', 'Только сильная: у ушедших'), Column('ssb', 'Только сильная: у остальных'),
            Column('slift', 'Только сильная: во сколько раз чаще')],
            note='Скважино-год — одна скважина в одном проверяемом году (2022–2025): «ушедшие в КР» — скважино-годы, когда в этом году был КР, «остальные» — все прочие. '
                 'Механизм полезен, если у ушедших в КР он встречается заметно чаще (отношение заметно больше 1). Выборка мала: смотрите как подсказку.'))
    return out


def fund_tables(rows: list[dict[str, Any]]) -> list[Table]:
    """Кандидаты в КРС по фонду: скважина, группа, сумма улик, механизмы и подсказка операции (только скважины хотя бы с одной уликой)."""
    shown = [r for r in rows if r['score'] > 0]
    if not shown:
        return []
    frame = pd.DataFrame({'well': [r['well'] for r in shown], 'group': [r['group'] for r in shown], 'score': [round(r['score'], 1) for r in shown],
                          'mechanisms': [r['mechanisms'] for r in shown], 'recommendation': [r['recommendation'] for r in shown],
                          'last_kr': [('КР ' + str(r['last_kr'])) if r.get('last_kr') else 'КР не было' for r in shown],
                          'perf': [None if r.get('perf') is None else round(r['perf']) for r in shown],
                          'who': ['решение инженера' if r['manual'] else 'авто' for r in shown]})
    return [Table('passport-fund', 'Кандидаты в КРС по фонду (подсказка)', frame, [
        Column('well', 'Скважина'), Column('group', 'Группа'), Column('score', 'Сумма улик'), Column('mechanisms', 'Причина отметки: механизмы'),
        Column('recommendation', 'Что делать (подсказка)'), Column('last_kr', 'Ремонтировали'),
        Column('perf', 'Средний расход, последний сезон к предыдущему', '%', 0, 'number'), Column('who', 'Кто решил')],
        note='Сильная улика = 2 балла, слабая = 1, с весом свежести. Это подсказка для отбора: решает инженер, его решения по механизмам учтены. '
             'Скважины без КР — кандидаты, которых план ремонтов мог не покрыть (план ограничен ресурсами). Падение среднего расхода — индикатор, на расход влияют режим и давление.')]


def sweep_tables(sweep: dict[str, list[dict[str, Any]]]) -> list[Table]:
    """Перебор порогов на истории: устойчивые наборы и текущий набор (общая таблица ядра)."""
    pct = lambda v: '' if v is None else f'{v * 100:.0f} %'
    out = []
    for key, title in (('depression', 'Перебор порогов: превышение предельной депрессии'), ('throttle', 'Перебор порогов: ограничение устья / КРУ')):
        rows = sweep.get(key) or []
        if not rows:
            continue
        frame = pd.DataFrame({'label': [r['label'] + ('  ← сейчас' if r['current'] else '') for r in rows], 'n': [r['n'] for r in rows],
                              'all': [pct(r['share_all']) for r in rows], 'rep': [pct(r['share_repaired']) for r in rows], 'oth': [pct(r['share_other']) for r in rows],
                              'lift': ['' if r['lift'] is None else f"{r['lift']:.1f}" for r in rows], 'prec': [pct(r['precision']) for r in rows],
                              'stab': [pct(r.get('stability')) for r in rows]})
        out.append(Table(f'passport-sweep-{key}', title, frame, [
            Column('label', 'Пороги'), Column('n', 'Скважино-лет с данными'), Column('all', 'Срабатывает у'), Column('stab', 'Устойчивость к сдвигу порога'),
            Column('rep', 'У ушедших в КР'), Column('oth', 'У остальных'), Column('lift', 'Во сколько раз чаще у ушедших в КР'), Column('prec', 'Точность среди сработавших')],
            note='Первыми идут наборы, устойчивые к сдвигу порога на шаг, затем те, где механизм заметно чаще у ушедших в КР (история КР — слабая проверка: план ремонтов ограничен ресурсами). Показаны лучшие наборы и текущий. '
                 'Пороги применяются только вручную кнопкой под таблицами. Выборка мала: смотрите как подсказку.'))
    return out


def elpro_pressure_chart(data: dict[str, Any] | None) -> Chart | None:
    """Давление ЭЛПРО скважины, медиана по группе и замеры среднего Рпл на одной оси, расход скважины на правой; полосами — аномалии давления ЭЛПРО."""
    ser = (data or {}).get('series') or {}
    if not ser.get('date') or not any(v is not None for v in ser.get('p', [])):
        return None
    x = pd.to_datetime(ser['date']).to_numpy()
    chart = Chart('passport-elpro-p', 'Давление ЭЛПРО: скважина, группа, пластовое и расход', Axis('Дата', scale='time'), Axis('Давление', 'кгс/см²', from_zero=False),
                  y2=Axis('Расход скважины', 'тыс. м³/сут', from_zero=True, color='#7a8a90'), crosshair=True)
    chart.series.append(Series('Давление ЭЛПРО скважины', x, _f(ser['p']), 'line', group='Давление ЭЛПРО скважины', color='#08519c', width=1.8))
    if any(v is not None for v in ser.get('grp_p', [])):
        chart.series.append(Series('Давление ЭЛПРО: медиана по группе', x, _f(ser['grp_p']), 'line', group='Давление ЭЛПРО: медиана по группе', color='#e08214', width=1.4))
    pr = [(d, v) for d, v in zip(ser['date'], ser.get('p_res', [])) if v is not None]
    if pr:
        chart.series.append(Series('Пластовое (среднее по замерам)', pd.to_datetime([d for d, _ in pr]).to_numpy(), np.array([v for _, v in pr]), 'points',
                                   group='Пластовое (среднее по замерам)', color='#c0392b'))
    if any(v is not None for v in ser.get('q', [])):
        chart.series.append(Series('Расход скважины', x, _f(ser['q']), 'line', axis='y2', group='Расход скважины', color='#7a8a90', width=1.1))
    rows = (data or {}).get('rows') or []
    if rows:
        chart.style = {'annotations': [{'kind': 'vband', 'value': pd.to_datetime(r['start'], dayfirst=True).strftime('%Y-%m-%d'),
                                        'to': pd.to_datetime(r['end'], dayfirst=True).strftime('%Y-%m-%d'),
                                        'text': f"Давление ЭЛПРО {r['direction']} на {abs(r['dp']):.1f}: {r['cause']}", 'color': '#c0392b'} for r in rows]}
    return chart


def elpro_anomaly_table(data: dict[str, Any] | None) -> Table | None:
    rows = (data or {}).get('rows') or []
    if not rows:
        return None
    pct = lambda k: _f([r[k] for r in rows])
    frame = pd.DataFrame({'start': [r['start'] for r in rows], 'end': [r['end'] for r in rows], 'peak': [r['peak'] for r in rows], 'dp': pct('dp'),
                          'dp_group': pct('dp_group'), 'dp_res': pct('dp_res'), 'dq': pct('dq'), 'dq_group': pct('dq_group'), 'dq_obj': pct('dq_obj'),
                          'cause': [r['cause'] for r in rows]})
    return Table('passport-elpro-anomalies', 'Аномалии давления ЭЛПРО', frame, [
        Column('start', 'С'), Column('end', 'По'), Column('peak', 'Пик'), Column('dp', 'Сдвиг давления ЭЛПРО', 'кгс/см²', 1, 'number'),
        Column('dp_group', 'Сдвиг по группе', 'кгс/см²', 1, 'number'), Column('dp_res', 'Изменение Рпл', 'кгс/см²', 1, 'number'),
        Column('dq', 'Расход скважины', '%', 0, 'number'), Column('dq_group', 'Расход группы', '%', 0, 'number'), Column('dq_obj', 'Расход объекта', '%', 0, 'number'),
        Column('cause', 'Вероятная причина')],
        note='Сдвиг — медиана за 7 суток против медианы за 28 суток перед ней. Аномалия — сдвиг давления ЭЛПРО от 2 кгс/см². Причина — подсказка: решает инженер.')


def depression_chart(dep: dict[str, Any] | None) -> Chart | None:
    """Депрессия Рпл − Рзаб на каждую дату замера Рпл (когда скважина работала) по времени: точки на линии предела типа забоя; превышения — красным."""
    pts = [(p, r['period']) for r in (dep or {}).get('rows', []) for p in r.get('points', [])]
    if not pts:
        return None
    pts.sort(key=lambda x: x[0]['day'])
    when = pd.to_datetime([p['day'] for p, _ in pts]).to_numpy()
    chart = Chart('passport-depression', 'Депрессия на даты замеров пластового давления (по ГДИ)', Axis('Дата замера Рпл', scale='time'),
                  Axis('Депрессия Рпл − Рзаб', 'кгс/см²', from_zero=True), crosshair=True)
    labels = [f"Депрессия {p['dep']:.2f} кгс/см² · Рпл {p['p_res']:.1f} · Q {p['q']:.1f} тыс. м³/сут · сезон {per}" for p, per in pts]
    chart.series.append(Series('Депрессия на дату замера', when, np.array([p['dep'] for p, _ in pts]), 'line', group='Депрессия на дату замера', color='#08519c',
                               labels=labels, width=1.4))
    over = [(p, per) for p, per in pts if p['over']]
    if over:
        chart.series.append(Series('Выше предела', pd.to_datetime([p['day'] for p, _ in over]).to_numpy(), np.array([p['dep'] for p, _ in over]), 'points',
                                   group='Выше предела', color='#c0392b', labels=[f"Выше предела: {p['dep']:.2f} на {p['date']}" for p, _ in over]))
    if dep.get('limit'):
        name = f"Предел {dep['limit']:g} кгс/см²"
        chart.series.append(Series(name, when, np.full(len(when), float(dep['limit'])), 'line', color='#c0392b', dash='dash', width=2, group=name))
    return chart


def depression_table(dep: dict[str, Any] | None) -> Table | None:
    """По сезонам: дат замера при работе, дат выше предела, доля, максимум депрессии (на какую дату и при каком Рпл) и статус."""
    rows = (dep or {}).get('rows') or []
    if not rows:
        return None
    frame = pd.DataFrame({'period': [r['period'] for r in rows], 'n': [r['n'] for r in rows], 'n_over': [r['n_over'] for r in rows],
                          'share': _f([None if r['share_over'] is None else r['share_over'] * 100 for r in rows]),
                          'dep_max': _f([r['dep_max'] for r in rows]), 'p_date': [r['p_date'] for r in rows], 'p_res': _f([r['p_res'] for r in rows]),
                          'dep_mean': _f([r['dep_mean'] for r in rows]), 'q_max': _f([r['q_max'] for r in rows]), 'limit': _f([r['limit'] for r in rows]),
                          'status': [r['status'] for r in rows], 'note': [r['note'] for r in rows]})
    bad = [i for i, r in enumerate(rows) if r['status'] == 'превышен']
    return Table('passport-depression', 'Депрессия по сезонам отбора (на даты замеров Рпл)', frame, [
        Column('period', 'Сезон'), Column('n', 'Дат замера при работе', 'шт.', 0, 'number'), Column('n_over', 'Из них выше предела', 'шт.', 0, 'number'),
        Column('share', 'Доля выше предела', '%', 0, 'number'), Column('dep_max', 'Максимум депрессии', 'кгс/см²', 2, 'number'), Column('p_date', 'Дата максимума'),
        Column('p_res', 'Рпл на эту дату', 'кгс/см²', 1, 'number'), Column('dep_mean', 'Средняя депрессия', 'кгс/см²', 2, 'number'),
        Column('q_max', 'Q в день максимума', 'тыс. м³/сут', 1, 'number'), Column('limit', 'Предел', 'кгс/см²', 1, 'number'), Column('status', 'Статус'),
        Column('note', 'Примечание')], styles=[CellStyle(bad, font='c0392b')] if bad else [],
        note='Депрессия — Рпл − Рзаб (не квадрат), обратный пересчёт по последнему надёжному ГДИ: Рзаб² = Рпл² − (a·q + b·q²) на каждую дату замера Рпл, '
             'когда скважина работала (расход этой даты). Оценка, не замер; предел и тип забоя задаёт инженер.')


def blocks(card: dict[str, Any]) -> tuple[list[Chart], list[Table]]:
    charts = tile_charts(card.get('tiles')) + [c for c in (depression_chart(card.get('depression')), elpro_pressure_chart(card.get('elpro_p')), seasons_chart(card['seasons']), daily_chart(card['daily'], card.get('elpro_cru')), gdi_chart(card['gdi_diagrams'])) if c]
    tables = [t for t in (assess_table(card.get('assess') or []), depression_table(card.get('depression')), seasons_table(card['seasons']), elpro_table(card.get('elpro') or []), elpro_anomaly_table(card.get('elpro_p')), gdi_table(card['gdi']), krs_table(card['krs'])) if t]
    return charts, tables


def search_tables(result: dict[str, Any]) -> list[Table]:
    """Итог автоперебора критериев вывода в КРС (общая таблица ядра): устойчивость, деление отмеченных на ремонтировавшиеся и нет, реальное падение расхода,
    история КР (слабая проверка); по лучшему варианту и текущим критериям — отмеченные скважины с причинами."""
    rows = result.get('rows') or []
    if not rows:
        return []
    pct = lambda v: '' if v is None else f'{v * 100:.0f} %'
    num = lambda v: '' if v is None else f'{v:.1f}'
    fit, test = result.get('fit_years') or [], result.get('test_years') or []

    def split(r):
        rv = r.get('review')
        return f"{rv['flagged_repaired']} / {rv['flagged_not_repaired']}" if rv else ''

    def drop(r, key):
        p = (r.get('review') or {}).get(key) or {}
        return '' if not p.get('n') else f"{pct(p['drop_share'])} (у {p['n']})"

    frame = pd.DataFrame({'text': [r['text'] + ('  ← сейчас' if r['current'] else '') for r in rows],
                          'stab': [pct(r.get('stability')) for r in rows], 'persist': [pct((r.get('review') or {}).get('persistence')) for r in rows],
                          'flag': [pct(r['flagged']) for r in rows], 'split': [split(r) for r in rows],
                          'drop_not': [drop(r, 'perf_flagged_not_repaired') for r in rows], 'drop_rest': [drop(r, 'perf_not_flagged') for r in rows],
                          'dep': [pct(r['dep_share']) for r in rows], 'el': [pct(r['el_share']) for r in rows],
                          'fit_lift': [num(r['fit_lift']) for r in rows], 'fit_prec': [pct(r['fit_precision']) for r in rows],
                          'test_lift': [num(r['test_lift']) for r in rows], 'test_prec': [pct(r['test_precision']) for r in rows],
                          'stable': [f"{r['years_better']} из {r['years']}" for r in rows], 'worst': [num(r['worst_lift']) for r in rows]})
    cols = [Column('text', 'Вариант критериев'), Column('stab', 'Устойчивость к сдвигу порога'), Column('persist', 'Те же скважины из года в год'),
            Column('flag', 'Скважин с любой уликой'), Column('split', 'Отмечено: ремонтировались / нет (скважино-лет)'),
            Column('drop_not', 'Расход упал ≥ 10 %: отмеченные без КР'), Column('drop_rest', 'Расход упал ≥ 10 %: не отмеченные без КР'),
            Column('dep', 'Депрессия срабатывает у'), Column('el', 'ЭЛПРО срабатывает у'),
            Column('fit_lift', f'История КР, лучше случайного, подбор ({", ".join(map(str, fit))})'), Column('fit_prec', 'История КР, точность, подбор')]
    if test:
        cols += [Column('test_lift', f'История КР, лучше случайного, проверка ({", ".join(map(str, test))})'), Column('test_prec', 'История КР, точность, проверка')]
    cols += [Column('stable', 'История КР: лет лучше случайного'), Column('worst', 'История КР: худший год, во сколько раз')]
    out = [Table('passport-search', f'Автоперебор критериев вывода в КРС (перебрано вариантов: {result.get("tried", 0)})', frame, cols,
                 note=' '.join(result.get('notes') or []))]
    shown = [(r, 'сейчас' if r['current'] else 'лучший вариант') for r in rows if (r.get('review') or {}).get('entries')]
    if shown:
        items = [(label, r['review']['entries'], r['review']) for r, label in shown]
        flat = [(label, e) for label, entries, _ in items for e in entries]
        wells = pd.DataFrame({'variant': [x[0] for x in flat], 'year': [x[1]['year'] for x in flat], 'well': [x[1]['well'] for x in flat],
                              'reasons': [x[1]['reasons'] for x in flat], 'kr': ['ремонтировали' if x[1]['repaired'] else 'без КР' for x in flat],
                              'perf': [x[1]['perf'] for x in flat]})
        out.append(Table('passport-search-wells', 'Отмеченные скважины: причины, ремонтировали или нет, изменение расхода', wells, [
            Column('variant', 'Критерии'), Column('year', 'Год проверки', '', 0, 'number'), Column('well', 'Скважина'), Column('reasons', 'Причина отметки'),
            Column('kr', 'КР в проверяемом периоде'), Column('perf', 'Средний расход сезона после даты к сезону до неё', '%', 0, 'number')],
            note='«Без КР» — отмеченные скважины, которые не ремонтировали: кандидаты, которых план ремонтов мог не покрыть. Изменение среднего расхода — индикатор, '
                 'на расход влияют режим и давление. Решение за инженером.'))
    return out
