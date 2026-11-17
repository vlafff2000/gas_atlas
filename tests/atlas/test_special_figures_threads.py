"""Рисунки тепловых карт, полос и стопок строятся в параллельных запросах (предпросмотр «Любого графика» при каждой правке настроек):
один запрос не должен закрывать чужие рисунки (``plt.close('all')``) — иначе у соседнего падало «get_renderer»."""
import threading

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from atlas import chart_special
from atlas.contract import Axis, Chart, HeatMap


def _heat():
    h = HeatMap(['ГСП 1', 'ГСП 2'], ['2023/24', '2024/25'], [[10, 20], [None, 5]], [['10', '20'], ['', '5']], 'Скважин')
    return Chart('x', 'Карта', Axis('Сезон'), Axis('ГСП'), heat=h)


def test_building_a_special_figure_does_not_close_foreign_figures():
    foreign = plt.figure()
    try:
        chart_special.figure_file(_heat(), 'png', 150)
        assert plt.fignum_exists(foreign.number)
    finally:
        plt.close(foreign)


def test_parallel_previews_with_scene_and_table_font_all_succeed():
    errors = []

    def work():
        try:
            for _ in range(3):
                chart_special.figure_file(_heat(), 'png', 150, {'table_font_size': 14, 'cell_size': 14}, [])
        except Exception as exc:     # noqa: BLE001
            errors.append(repr(exc))
    threads = [threading.Thread(target=work) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == []
