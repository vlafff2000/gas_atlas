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
