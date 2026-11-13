"""Word: жёсткая проверка раскладки (``word_export.check_layout``): график не шире ячейки и не выше места на листе, ряды
помещаются на лист, разрешение достаточное. Находки — отчёт инженеру: документ строится в любом случае."""
from __future__ import annotations

import struct
import zlib

import pytest

from atlas import word_export
from atlas.word_export import Item, Layout, check_layout, merge_checks


def _png(width_px: int, height_px: int = 10) -> bytes:
    """Минимальный PNG нужного размера: проверка читает только ширину из заголовка."""
    return b'\x89PNG\r\n\x1a\n' + struct.pack('>I', 13) + b'IHDR' + struct.pack('>II', width_px, height_px) + b'\x08\x00\x00\x00\x00' + struct.pack('>I', zlib.crc32(b'x'))


def _item(name='График', w=100.0, h=60.0, png=b''):
    return Item(name, 'Рисунок ', 1, '', png=png, w=w, h=h)


def _codes(layout, items):
    return [f['code'] for f in check_layout(layout, items)]


def test_everything_in_place_gives_no_findings():
    lay = Layout()      # A4 книжная, поля 25 и 15 мм: ширина ячейки 170 мм
    assert check_layout(lay, [_item(w=170, h=100), _item(w=169.9, h=80)]) == []


@pytest.mark.parametrize('layout, item, codes', [
    (Layout(), _item(w=175), ['wider']),
    (Layout(), _item(w=170.1), []),      # округление не нарушение
    (Layout(), _item(h=400), ['taller']),
    (Layout(columns=3), _item(w=40, h=30), ['narrow']),      # третья часть листа: 40 мм
    (Layout(), _item(w=100, png=_png(300)), ['dpi']),      # 300 px на 100 мм ≈ 76 точек на дюйм
    (Layout(), _item(w=100, png=_png(1200)), []),
])
def test_item_rules(layout, item, codes):
    assert _codes(layout, [item]) == codes


def test_fixed_per_page_that_does_not_fit_is_reported_with_the_page():
    lay = Layout(per_page=3)      # 3 графика в одну колонку: по 100 мм не влезают в 257 мм
    items = [_item(f'г{i}', w=170, h=100) for i in range(3)]
    found = check_layout(lay, items)
    assert [f['code'] for f in found] == ['taller', 'page']      # и сам график выше доступного, и ряды вместе не умещаются
    assert found[1]['items'] == ['лист 1'] and found[1]['level'] == 'warn'
    assert check_layout(Layout(per_page=2), items[:2]) == []


def test_findings_collapse_per_code_with_names():
    found = check_layout(Layout(), [_item('а', w=175), _item('б', w=176), _item('в', w=100)])
    assert len(found) == 1 and found[0]['items'] == ['а', 'б']
    merged = merge_checks(found + check_layout(Layout(), [_item('б', w=175), _item('г', w=177)]))
    assert merged[0]['items'] == ['а', 'б', 'г']
    lines = word_export.check_summary(merged)
    assert lines[0].endswith('Затронуто: 3 (а, б, г).')


def test_real_render_fits_its_cell():
    """Графики, нарисованные ``render_png`` в размер ячейки, проверку проходят при любом числе колонок."""
    from atlas import render
    from atlas.contract import Axis, Chart, Series
    chart = Chart('t', 'Проба', Axis('Дата', scale='time'), Axis('Значение'))
    chart.series.append(Series('а', ['2024-01-01', '2024-02-01', '2024-03-01'], [1.0, 3.0, 2.0], 'line'))
    for columns in (1, 2):
        lay = Layout(columns=columns, dpi=150)
        item = _item()
        cap = word_export.caption_height(lay, item.text, lay.cell())
        item.png, item.w, item.h = word_export.render_png(render.to_plotly(chart), lay, cap)
        assert _codes(lay, [item]) == (['narrow'] if columns == 2 and item.w < word_export.MIN_WIDTH else []), (columns, item.w)
