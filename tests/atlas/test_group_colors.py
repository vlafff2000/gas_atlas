from atlas import group_colors as gc
from atlas.engine.modules.charts import group_palette


def test_group_chart_colors_are_stable_across_charts(tmp_path, monkeypatch):
    monkeypatch.setenv('PXG_HOME', str(tmp_path))
    gc.set_known_groups([f'ГСП-{i}' for i in range(1, 10)])
    try:
        small = group_palette(['ГСП 7', 'ГСП-2'])
        full = group_palette([f'ГСП-{i}' for i in range(1, 10)])
        assert small['ГСП-2'] == full['ГСП-2'] and small['ГСП 7'] == full['ГСП-7']
        assert len(set(full.values())) == 9
    finally:
        gc.set_known_groups([])


def test_group_charts_use_group_colors():
    import pandas as pd
    from atlas.modules import an_charts
    gc.set_known_groups(['ГСП-1', 'ГСП-2', 'ГСП-3'])
    try:
        means = pd.DataFrame({'scope': ['ГСП-3', 'ГСП-1', 'Объект'] * 2, 'period': ['январь'] * 3 + ['февраль'] * 3,
                              'mean': [1.0, 2.0, 3.0, 1.5, 2.5, 4.0]})
        chart = an_charts.monthly_groups_chart('withdrawal', '2024/25', means)
        full = gc.group_colors(['ГСП-1', 'ГСП-2', 'ГСП-3'], {})
        assert {s.name: s.color for s in chart.series} == {'ГСП-3': full['ГСП-3'], 'ГСП-1': full['ГСП-1']}
    finally:
        gc.set_known_groups([])
