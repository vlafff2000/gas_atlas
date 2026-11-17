"""Таблица под графиком: в ячейках число скважин или их номера (общая настройка «table_cells», экран и файл)."""
import pandas as pd

from atlas import chart_style
from atlas.contract import ChartTable
from atlas.modules import gdi_summary as gs


def _frame():
    return pd.DataFrame({'well': ['10', '2', '33', '4'], 'category': ['А', 'А', 'А', 'Б'],
                         'verdict': [gs.VERDICT_UP, gs.VERDICT_UP, gs.VERDICT_DOWN, gs.VERDICT_UP], 'change': [10.0, 12.0, -20.0, 40.0]})


def test_stacked_table_carries_wells_per_cell_in_natural_order():
    t = _frame()
    chart = gs.stacked('x', 'T', ['А', 'Б'], {('А', gs.VERDICT_UP): 2, ('Б', gs.VERDICT_UP): 1, ('А', gs.VERDICT_DOWN): 1},
                       (gs.VERDICT_UP, gs.VERDICT_DOWN), gs.VERDICT_COLORS, 'Категория',
                       wells=gs.members(t, 'category', ['А', 'Б'], (gs.VERDICT_UP, gs.VERDICT_DOWN)))
    assert chart.table.wells[0][0] == ['2', '10'] and chart.table.wells[1][0] == ['33']
    assert chart.table.cells[0][0] == '2'                       # число — как раньше


def test_shown_switches_between_count_and_wells_and_wraps():
    table = ChartTable(['р'], ['а', 'б'], [['3', '0']], wells=[[['1', '2', '3', '40', '50', '60', '70', '80'], []]])
    assert table.shown(None) == [['3', '0']] and table.shown('count') == [['3', '0']]
    shown = table.shown('wells')
    assert shown[0][0] == '1, 2, 3, 40, 50, 60,\n70, 80' and shown[0][1] == '0'      # пустая ячейка остаётся числом


def test_setting_is_cleaned_and_reaches_the_file_table():
    assert chart_style.clean_chart({'table_cells': 'wells'}).get('table_cells') == 'wells'
    from atlas.render import to_plotly
    from atlas.contract import Axis, Chart, Series
    chart = Chart('c', 'T', Axis('X', scale='category', categories=['а']), Axis('Y'), style={'table_cells': 'wells'})
    chart.series.append(Series('р', ['а'], [2.0], 'bar', stack='s', segments=['2']))
    chart.table = ChartTable(['р'], ['а'], [['2']], wells=[[['7', '9']]])
    cells = [t for t in to_plotly(chart).data if t.type == 'table'][0].cells.values
    assert cells[1] == ['7, 9']
