"""Конструкции из Word: загрузка столбцов «Ресурс» и «Комплект», пометка скважины по всем датам, вывод для ГДИ."""
import datetime as dt

import pandas as pd

from atlas.engine.core import loader
from atlas.engine.modules import well_analysis as wa


def book(path):
    cols = ['Скважина', 'Дата конструкции', 'Элемент', 'Верх интервала, м', 'Низ интервала, м', 'Наружный диаметр, мм',
            'Внутренний диаметр, мм', 'Комментарий', 'Комплект', 'Ресурс', 'Строка перечня']
    rows = [['500', dt.date(2013, 5, 29), 'Эксплуатационная колонна', 0, 784, 245, None, '', 'Ресурс-4', 'Да', 'таблица 2, строка 2'],
            ['500', dt.date(2013, 5, 29), 'Фильтр', 785, 795, None, None, '', 'Ресурс-4', 'Да', 'таблица 2, строка 2'],
            ['500', dt.date(2016, 6, 10), 'Эксплуатационная колонна', 0, 790, 245, None, '', '', '', 'таблица 2, строка 3'],
            ['512', dt.date(2018, 3, 15), 'Эксплуатационная колонна', 0, 900, 245, None, '', '', '', 'таблица 2, строка 4']]
    with pd.ExcelWriter(path) as xw:
        pd.DataFrame(rows, columns=cols).to_excel(xw, sheet_name='Конструкция', index=False)


def test_resource_loaded_and_marked(tmp_path):
    p = tmp_path / 'к.xlsx'
    book(p)
    r = loader.load_file(str(p))
    cons = r.frames['construction']
    assert {'resource', 'kit'} <= set(cons.columns) and not r.issues
    assert cons.group.eq('Без группы').all() or 'group' in cons       # «Строка перечня» не становится группой
    assert not cons.group.astype(str).str.contains('таблица').any()
    frames = {'construction': cons}
    info = wa.resource_info(frames, '500')
    assert info['flag'] and info['kits'] == ['Ресурс-4'] and info['dates'] == ['29.05.2013']      # последняя конструкция уже без пометки, а на скважине она была
    assert not wa.resource_info(frames, '512')['flag']
    assert not wa.resource_info(frames, '500', dt.date(2012, 1, 1))['flag']
    out = wa.signals(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), 10, info)
    assert any('ГДИ' in x for x in out['Что проверить'])
