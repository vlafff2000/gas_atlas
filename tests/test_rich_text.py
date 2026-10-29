"""Подписи с индексами: текст без тегов для имён файлов и листов Excel, теги для Plotly."""
import io
import zipfile

from atlas.contract import Axis, Chart, Series
from atlas.render import chart_file
from atlas.rich_text import mpl_text, plain


def test_plain_removes_only_index_tags():
    assert plain('CO<sub>2</sub>, м<sup>3</sup>') == 'CO2, м3'
    assert plain('Рпл, кгс/см²') == 'Рпл, кгс/см²'
    assert plain('<b>жирный</b>') == '<b>жирный</b>'      # другие теги не трогаем
    assert plain(None) == ''


def test_xlsx_file_name_and_sheet_use_plain_title():
    chart = Chart(id='t', title='Дебит Q<sub>ж</sub>', x=Axis(label='Время'), y=Axis(label='Q<sub>ж</sub>', unit='м<sup>3</sup>/сут'),
                  series=[Series(name='Q<sub>ж</sub>', x=['2026-01-01', '2026-01-02'], y=[1.0, 2.0])])
    body, name, _ = chart_file(chart, 'xlsx', 200)
    assert name == 'Дебит Qж.xlsx'
    with zipfile.ZipFile(io.BytesIO(body)) as zf:
        parts = {n: zf.read(n).decode('utf-8') for n in zf.namelist() if n.endswith('.xml')}
    assert any('Дебит Qж' in text for text in parts.values())         # заголовок диаграммы в файле
    assert not any('sub&gt;' in text or 'sup&gt;' in text for text in parts.values())


def test_mpl_text_turns_index_tags_into_mathtext_and_drops_other_tags():
    assert mpl_text('Рпл, кгс/см²') == 'Рпл, кгс/см²'                     # без индексов строка не меняется
    assert mpl_text('Q<sub>ж</sub>, м<sup>3</sup>') == '$\\mathregular{Q_{ж},\\ м^{3}}$'
    assert mpl_text('<b>x</b> 50%') == 'x 50%'
    assert mpl_text('a<sup>5</sup> 50%') == '$\\mathregular{a^{5}\\ 50\\%}$'
    assert mpl_text(None) == ''
