"""Какие наборы данных оставить на графике: выбор работает у любого графика, в том числе у стопок с числами в сегментах и таблицей
под графиком; пустые наборы в легенде по умолчанию не показываются (решает инженер: можно вернуть)."""
import numpy as np

from atlas import chart_view, export_any, legend_empty
from atlas.contract import Axis, Chart, ChartTable, Result, Series


def _stack() -> Chart:
    cats = ['А', 'Б']
    chart = Chart('prog', 'Выполнение', Axis('Причина', scale='category', categories=cats), Axis('Скважин', 'ед.'))
    for name, values in (('выполнено', [2.0, 1.0]), ('выполнено (выбрано вручную)', [0.0, 0.0]), ('не выполнено', [1.0, 3.0])):
        chart.series.append(Series(name, cats, np.array(values), 'bar', stack='s', segments=[str(int(v)) if v else '' for v in values]))
    chart.table = ChartTable([s.name for s in chart.series], cats, [['2', '1'], ['0', '0'], ['1', '3']], wells=[[['1', '2'], ['3']], [[], []], [['4'], ['5', '6', '7']]])
    return chart


def test_hidden_series_leaves_stack_and_its_table_row():
    out = chart_view.apply_view(_stack(), {'hidden': ['выполнено (выбрано вручную)']})
    assert [s.name for s in out.series] == ['выполнено', 'не выполнено']
    assert out.table.rows == ['выполнено', 'не выполнено'] and out.table.cells == [['2', '1'], ['1', '3']]
    assert out.table.wells == [[['1', '2'], ['3']], [['4'], ['5', '6', '7']]]


def test_special_chart_with_hidden_series_is_exported_without_it():
    data, *_ = export_any.export(_stack(), {'format': 'png', 'view': {'hidden': ['выполнено (выбрано вручную)']}})
    assert data[:4] == b'\x89PNG'


def test_empty_sets_do_not_show_in_legend_by_default():
    result = legend_empty.apply(Result(charts=[_stack()]))
    flags = {s.name: s.legend for s in result.charts[0].series}
    assert flags == {'выполнено': True, 'выполнено (выбрано вручную)': False, 'не выполнено': True}


def test_all_zero_line_is_data_and_stays_in_legend():
    chart = Chart('l', 'T', Axis('X', scale='category', categories=['а']), Axis('Y'))
    chart.series.append(Series('нулевой расход', ['а'], np.array([0.0]), 'line'))
    chart.series.append(Series('пусто', ['а'], np.array([np.nan]), 'line'))
    flags = {s.name: s.legend for s in legend_empty.apply(Result(charts=[chart])).charts[0].series}
    assert flags == {'нулевой расход': True, 'пусто': False}


def test_series_of_lists_like_box_plots_are_left_alone():
    chart = Chart('b', 'T', Axis('X', scale='category', categories=['а']), Axis('Y'))
    chart.series.append(Series('ящик', ['а'], [[1.0, 2.0, 3.0]], 'box'))
    chart.series.append(Series('второй', ['а'], [[2.0, 3.0]], 'box'))
    assert all(s.legend for s in legend_empty.apply(Result(charts=[chart])).charts[0].series)
