"""«Авторский надзор»: фонд скважин за сезон (табл. 1.4–1.6) и отклонения плана (рис. 1.8) — расчёт на малом примере вручную."""
import pandas as pd
import pytest

from atlas.modules import an_report, an_wells

MAPPING = {'1': {'group': 'ГСП-1'}, '2': {'group': 'ГСП 1'}, '3': {'group': 'ГСП_2'}, '4': {'group': 'ГСП_2'}}
SCOPES = an_report.well_scopes(MAPPING, ['1', '2', '3', '4'])


def production(rows):
    frame = pd.DataFrame(rows, columns=['well', 'date', 'q'])
    frame['date'] = pd.to_datetime(frame.date)
    frame['kind'] = 'withdrawal'
    frame['period'] = '2023-2024'
    return frame


# м³/сут. Скв. 1 — 200 тыс. (выше 100), скв. 2 — 50 тыс. (один рабочий день), скв. 3 и 4 — нулевые за сезон.
PROD = production([
    ('1', '2024-02-01', 150000), ('1', '2024-02-02', 250000),
    ('2', '2024-02-01', 50000), ('2', '2024-02-02', 0),
    ('3', '2024-02-01', 0), ('3', '2024-02-02', 0),
    ('4', '2024-02-01', 0),
])


def test_season_wells_counts_working_days_and_mean_rate():
    wells = an_wells.season_wells(PROD, 'withdrawal', '2023-2024').set_index('well')
    assert wells.loc['1', 'days'] == 2 and wells.loc['1', 'rate'] == pytest.approx(200000)
    assert wells.loc['2', 'days'] == 1                      # 02.02 с нулём — не сутки с расходом
    assert wells.loc['3', 'days'] == 0 and wells.loc['4', 'days'] == 0
    assert wells.loc['1', 'gas'] == pytest.approx(400000)


def test_fund_table_by_group_and_total():
    fund = an_wells.fund_table(an_wells.season_wells(PROD, 'withdrawal', '2023-2024'), SCOPES).set_index('group')
    assert fund.loc[an_wells.TOTAL, ['fund', 'working']].tolist() == [4, 2]
    assert fund.loc[an_wells.TOTAL, 'percent'] == pytest.approx(50)
    assert fund.loc['ГСП 1', ['fund', 'working']].tolist() == [2, 2]     # «ГСП-1» и «ГСП 1» — одна группа
    assert fund.loc['ГСП 2', ['fund', 'working']].tolist() == [2, 0]
    assert fund.loc['ГСП 2', 'percent'] == 0


def test_class_table_lists_well_numbers_in_brackets():
    classes = an_wells.class_table(an_wells.season_wells(PROD, 'withdrawal', '2023-2024'), SCOPES).set_index('group')
    assert classes.loc[an_wells.TOTAL, 'zero'] == '2 (3, 4)'
    assert classes.loc[an_wells.TOTAL, 'low'] == '1 (2)'
    assert classes.loc[an_wells.TOTAL, 'high'] == '1 (1)'
    assert classes.loc['ГСП 1', 'zero'] == '0'
    assert classes.loc['ГСП 2', 'zero'] == '2 (3, 4)'


WATER = pd.DataFrame({'well': ['1', '1', '2', '3'], 'date': pd.to_datetime(['2024-02-01', '2024-02-02', '2024-02-01', '2024-02-02']),
                      'water_volume_m3': [300.0, 200.0, 100.0, 0.0]})


def test_water_factor_is_liters_per_thousand_cubic_meters():
    wells = an_wells.season_wells(PROD, 'withdrawal', '2023-2024')
    by_well = an_wells.water_by_well(WATER, wells, SCOPES, pd.Timestamp('2024-02-01'), pd.Timestamp('2024-02-02')).set_index('well')
    assert by_well.loc['1', 'water'] == 500
    assert by_well.loc['1', 'wf'] == pytest.approx(1250)     # 500 м³ на 400 тыс. м³ газа = 1,25 м³/тыс. м³ = 1250 л/тыс. м³
    assert by_well.loc['2', 'wf'] == pytest.approx(2000)


def test_water_table_and_extremes():
    wells = an_wells.season_wells(PROD, 'withdrawal', '2023-2024')
    by_well = an_wells.water_by_well(WATER, wells, SCOPES, pd.Timestamp('2024-02-01'), pd.Timestamp('2024-02-02'))
    table = an_wells.water_table(by_well).set_index('group')
    assert table.loc[an_wells.TOTAL, 'wet'] == '2 (1, 2)'
    assert table.loc[an_wells.TOTAL, 'wf_max'] == pytest.approx(2000) and table.loc[an_wells.TOTAL, 'wf_well'] == '2'
    assert table.loc['ГСП 2', 'wet'] == '0' and pd.isna(table.loc['ГСП 2', 'wf_max'])
    extremes = an_wells.water_extremes(by_well)
    assert extremes['wet_wells'] == 2 and extremes['wf_max_well'] == '2' and extremes['wf_max_group'] == 'ГСП 1'


def test_no_water_volume_means_no_water_table():
    wells = an_wells.season_wells(PROD, 'withdrawal', '2023-2024')
    assert an_wells.water_by_well(None, wells, SCOPES, pd.Timestamp('2024-02-01'), pd.Timestamp('2024-02-02')) is None
    rates_only = WATER.rename(columns={'water_volume_m3': 'water_rate'})
    assert an_wells.water_by_well(rates_only, wells, SCOPES, pd.Timestamp('2024-02-01'), pd.Timestamp('2024-02-02')) is None


def test_plan_deviation_extremes_by_hand():
    by_group = pd.DataFrame({'group': ['ГСП 1', 'ГСП 2', 'ГСП 3'], 'plan': [10.0, 10.0, 5.0],
                             'fact': [12.0, 7.0, 5.0], 'percent': [120.0, 70.0, 100.0], 'delta': [2.0, -3.0, 0.0]})
    ext = an_wells.deviation_extremes(by_group)
    assert ext['delta_max'] == 2 and ext['delta_max_group'] == 'ГСП 1'
    assert ext['delta_min'] == -3 and ext['delta_min_group'] == 'ГСП 2'
    assert ext['percent_max'] == 120 and ext['percent_min'] == 70 and ext['percent_min_group'] == 'ГСП 2'


def test_class_counts_seven_classes_boundary_goes_up():
    prod = production([('1', '2024-02-01', 100000), ('2', '2024-02-01', 99999), ('3', '2024-02-01', 300000), ('4', '2024-02-01', 0),
                       ('5', '2024-02-01', 250000), ('6', '2024-02-01', 149000)])
    mapping = {w: {'group': 'ГСП-1'} for w in '123456'}
    scopes = an_report.well_scopes(mapping, list('123456'))
    counts = an_wells.class_counts(an_wells.season_wells(prod, 'withdrawal', '2023-2024'), scopes).set_index('group')
    assert counts.loc[an_wells.TOTAL, list(an_wells.CLASS_KEYS)].tolist() == [1, 1, 2, 0, 0, 1, 1]   # 0 | <100 | 100–150 (100 и 149) | … | 250–300 | >300 (300)
    assert counts.loc['ГСП 1', list(an_wells.CLASS_KEYS)].sum() == 6
    assert counts.loc[an_wells.TOTAL, 'zero_numbers'] == '1 (4)'


def test_class_share_chart_percent_height_and_counts_inside():
    from atlas.modules import an_charts
    counts = an_wells.class_counts(an_wells.season_wells(PROD, 'withdrawal', '2023-2024'), SCOPES)
    chart = an_charts.class_share_chart('withdrawal', '2023-2024', counts, 'dot')
    assert chart.x.categories[-1] == an_wells.TOTAL and chart.callouts == 'dot'
    assert [sum(s.y[j] for s in chart.series) for j in range(len(chart.x.categories))] == pytest.approx([100.0] * 3)
    assert chart.table.cells[0] == ['0', '2', '2'] and chart.series[0].segments == ['', '2', '2']
    assert an_charts.class_share_chart('withdrawal', '2023-2024', counts, 'box').table is None


def test_class_share_chart_exports_with_callouts_and_table():
    from atlas import render
    from atlas.modules import an_charts
    counts = pd.DataFrame({'group': ['ГСП 1', an_wells.TOTAL], 'zero_numbers': ['0', '0'],
                           **{k: v for k, v in zip(an_wells.CLASS_KEYS, ([0, 0], [1, 1], [0, 0], [3, 3], [0, 0], [0, 0], [40, 40]))}})
    box = render.to_plotly(an_charts.class_share_chart('withdrawal', '2023-2024', counts, 'box'))
    assert [a.text for a in box.layout.annotations if a.bordercolor] == ['1', '1']      # узкий сегмент (1 из 44) — выноска в рамке
    dot = render.to_plotly(an_charts.class_share_chart('withdrawal', '2023-2024', counts, 'dot'))
    assert any(t.type == 'table' for t in dot.data) and [a.text for a in dot.layout.annotations] == ['●', '●']


def test_month_working_counts_wells_with_flow_in_each_month():
    prod = production([('1', '2024-02-01', 100), ('1', '2024-03-01', 0), ('2', '2024-02-01', 50), ('2', '2024-03-05', 70),
                       ('3', '2024-03-01', 0), ('4', '2024-02-10', 10)])
    mapping = {w: {'group': 'ГСП-1' if w in '12' else 'ГСП-2'} for w in '1234'}
    scopes = an_report.well_scopes(mapping, list('1234'))
    frame, labels = an_wells.month_working(prod, 'withdrawal', '2023-2024', scopes)
    assert labels == ['Фев.24', 'Мар.24']
    total = frame.set_index('group').loc[an_wells.TOTAL]
    assert total.fund == 4 and (total.m0, total.m1) == (3, 1)           # в феврале работали 1, 2, 4; в марте только 2
    assert frame.set_index('group').loc['ГСП 2', ['fund', 'm0', 'm1']].tolist() == [2, 1, 0]


def test_month_working_chart_has_group_table_under_bars():
    from atlas.modules import an_charts
    frame, labels = an_wells.month_working(PROD, 'withdrawal', '2023-2024', SCOPES)
    chart = an_charts.month_working_chart('withdrawal', '2023-2024', frame, labels)
    assert [s.name for s in chart.series] == ['Работало', 'Не работало'] and chart.table.swatches is False
    assert chart.table.columns == ['Фонд', *labels] and chart.table.rows[0] == an_wells.TOTAL
    assert chart.series[0].y[0] + chart.series[1].y[0] == 4             # работало + не работало = фонд
