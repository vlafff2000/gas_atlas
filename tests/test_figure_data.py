import io

import pandas as pd
import plotly.graph_objects as go

from atlas.engine.core.export import figure_bytes
from atlas.engine.core.figure_data import figure_table


def fig():
    f = go.Figure()
    f.add_scatter(x=pd.to_datetime(['2025-01-01', '2025-01-02']), y=[1.5, 2.5], name='Скв. 1')
    f.add_bar(x=['a', 'b'], y=[3, 4], name='Столбцы')
    f.add_scatter(x=[1], y=[1], name='скрыт', visible='legendonly')
    f.update_layout(title='Расход')
    return f


def test_table_rows_and_hidden_series():
    t = figure_table(fig())
    assert list(t['Ряд']) == ['Скв. 1', 'Скв. 1', 'Столбцы', 'Столбцы']
    assert set(t['График']) == {'Расход'}


def test_heatmap_by_cells():
    f = go.Figure(go.Heatmap(z=[[1, 2], [3, 4]], x=['a', 'b'], y=['r1', 'r2']))
    t = figure_table(f, 'Карта')
    assert len(t) == 4 and t['Z'].sum() == 10


def test_figure_bytes_xlsx_and_csv():
    xlsx = figure_bytes(fig(), 'xlsx')
    assert len(pd.read_excel(io.BytesIO(xlsx))) == 4
    csv = figure_bytes(fig(), 'csv')
    assert csv.startswith(b'\xef\xbb\xbf') and 'Скв. 1' in csv.decode('utf-8-sig')


def test_data_file_switches_to_csv_over_excel_limit(monkeypatch):
    from atlas import api_export
    monkeypatch.setattr(api_export, 'XLSX_ROWS', 3)
    assert api_export.data_file('d', figures=[('Г', fig())])[0] == 'd.csv'
    assert api_export.data_file('d', figures=[('Г', go.Figure(go.Scatter(x=[1], y=[2])))])[0] == 'd.xlsx'
