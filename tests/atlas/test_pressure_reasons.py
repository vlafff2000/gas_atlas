"""Подписи причин отсутствия замеров на динамике давлений: примечание из файла → подпись у точки без факта."""
import numpy as np
import pandas as pd

from atlas.engine.core.import_rules import pressure_table
from atlas.engine.modules import pressure_match as pm
from atlas.modules import pressure


def long_sheet():
    """Длинная таблица из месячных отчётов: дата, скважина, давление, примечание (как в базе замеров)."""
    return pd.DataFrame({
        'Дата': ['01.03.2024', '01.04.2024', '01.05.2024', '01.03.2024'],
        'Скважина': [101, 101, 101, 102],
        'Давление': [60.0, np.nan, np.nan, 55.0],
        'Примечание': ['', 'капитальный ремонт', 'н.д.', ''],
    })


def test_detect_and_normalize_keep_note_text():
    table = long_sheet()
    assert pm.detect_columns(table)['note'] == 'Примечание'
    norm = pm.normalize(table)
    assert list(norm.note) == ['', 'капитальный ремонт', 'н.д.', '']


def test_layout_spec_passes_note_through_import_rules():
    raw = pd.DataFrame([['Дата', 'Скважина', 'Давление', 'Примечание']] + long_sheet().values.tolist(), dtype=object)
    from atlas.engine.core.import_rules import pressure_layout
    layout = pressure_layout(raw)
    assert layout['mapping']['note'] == 3
    spec = {'enabled': True, 'valid': True, 'header': 0, 'mapping': layout['mapping'], 'wide': False,
            'datecol': 0, 'wellcols': [], 'names': {}, 'fond_pairs': []}
    data, cfg = pressure_table(raw, spec)
    assert cfg['note'] == 'Примечание'
    norm = pm.normalize(data, cfg)
    assert 'капитальный ремонт' in set(norm.note)


def test_pair_keeps_fact_note_and_gap_points_need_model():
    fact = pm.normalize(long_sheet())
    model = pd.DataFrame({'date': pd.to_datetime(fact.date), 'well': fact.well,
                          'value': [61.0, 58.0, np.nan, 54.0], '_row': range(4)})
    merged, _ = pm.pair(fact, model, 'Объект', 'Сценарий')
    source = merged.assign(object='Объект', scenario='Сценарий', group='Без группы')
    gaps = pressure.gap_points(source)
    # Без факта с примечанием и модели на дату остаётся одна точка: 01.04 (капитальный ремонт, модель 58).
    # 01.05 — модели нет, подписи не будет.
    assert list(gaps.note) == ['капитальный ремонт']
    assert list(gaps.model) == [58.0]


def test_gap_points_empty_without_note_column():
    source = pd.DataFrame({'object': ['O'], 'well': ['1'], 'date': [pd.Timestamp('2024-04-01')],
                           'fact': [np.nan], 'model': [1.0]})
    assert pressure.gap_points(source).empty


def test_reason_series_builds_captions_and_hover():
    from atlas.contract import Chart, Axis
    chart = Chart('pressure-time', 't', Axis('Дата', scale='time'), Axis('Давление', 'кгс/см²'))
    gaps = pd.DataFrame({'object': ['O'], 'well': ['101'], 'date': [pd.Timestamp('2024-04-01')],
                         'note': ['капитальный ремонт'], 'model': [58.0]})
    view = pd.DataFrame({'object': ['O', 'O'], 'well': ['101', '101'], 'date': [pd.Timestamp('2024-03-01'), pd.Timestamp('2024-05-01')]})
    pressure.reason_series(chart, gaps, view)
    series = chart.series[-1]
    assert series.legend is False
    assert series.captions == ['№101: капитальный ремонт']
    assert 'Замера нет: капитальный ремонт' in series.labels[0]
