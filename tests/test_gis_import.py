"""База ГИС в Атласе: распознавание таблиц выгрузки, чтение CSV, замена замеров по дате и распознавание в общем импорте.
Файлы — литеральные, записываются прямо здесь; реальных данных компании в репозитории нет."""
import pandas as pd
import pytest

from atlas.engine.core import gis_import as g
from atlas.imports import base_book

PACKS = 'well;date;season;pack;color;intervals;top_m;bottom_m;h_eff_m;kg_avg;floor_m;gvk_label;gvk_depth_m;gvk_abs_m;gvk_extra;altitude_m;altitude_sheet_m;perf_top_m;perf_bottom_m;sheet\n'


def _csv(text: str) -> bytes:
    return ('﻿' + text).encode('utf-8')          # выгрузка пишет UTF-8 с BOM


PACK_ROW = '115;2024-10-01;осень;верхняя;;2;1000,0;1001,5;1,5;0,30;12,0;ГВК;1000,5;-1000,5;;-999,0;;;;Лист 115\n'


def test_detect_recognises_each_export_table_by_header():
    obs = ['well', 'date', 'date_exact', 'season', 'status', 'status_text', 'date_quality', 'packs', 'sheet', 'sheet_row']
    intervals = ['well', 'date', 'season', 'pack', 'color', 'from_m', 'to_m', 'hi_m', 'kp', 'kg', 'h_eff_m', 'gvk_label',
                 'gvk_abs_m', 'gvk_extra', 'status', 'kg_text', 'note', 'sheet', 'sheet_row']
    packs = PACKS.strip().split(';')
    assert g.detect(packs) == 'gis_packs'
    assert g.detect(intervals) == 'gis_intervals'
    assert g.detect(obs) == 'gis_observations'
    assert g.detect(['well', 'date', 'q']) == ''


def test_read_parses_decimal_comma_and_keeps_well_as_text():
    table, frame, warnings = g.read('gis_packs.csv', _csv(PACKS + PACK_ROW))
    assert table == 'gis_packs' and warnings == []
    assert frame.loc[0, 'well'] == '115'
    assert frame.loc[0, 'date'] == pd.Timestamp('2024-10-01')
    assert frame.loc[0, 'gvk_abs_m'] == pytest.approx(-1000.5)
    assert frame.loc[0, 'kg_avg'] == pytest.approx(0.30)


def test_read_drops_rows_without_date_and_says_so():
    text = PACKS + PACK_ROW + PACK_ROW.replace('2024-10-01', '')
    _, frame, warnings = g.read('x.csv', _csv(text))
    assert len(frame) == 1
    assert warnings == ['Пропущено строк без скважины или даты: 1']


def test_read_manual_table_overrides_detection_and_reports_missing_columns():
    with pytest.raises(ValueError, match='нет колонок'):
        g.read('x.csv', _csv('well;date;q\n115;2024-10-01;5\n'), 'gis_packs')
    with pytest.raises(ValueError, match='Не похоже'):
        g.read('x.csv', _csv('well;date;q\n115;2024-10-01;5\n'))


def test_merge_replaces_same_well_and_date_and_keeps_others():
    old = pd.DataFrame({'well': ['115', '115', '113'], 'date': pd.to_datetime(['2024-10-01', '2025-03-01', '2024-10-01']),
                        'kg_avg': [0.1, 0.2, 0.3]})
    new = pd.DataFrame({'well': ['115'], 'date': pd.to_datetime(['2024-10-01']), 'kg_avg': [0.9]})
    out = g.merge(old, new)
    assert list(out['kg_avg']) == [0.3, 0.9, 0.2]               # 115 за 2024-10-01 заменён, прочее на месте (порядок: скважина, дата)
    kept = g.merge(old, new, keep_old=True)
    assert list(kept['kg_avg']) == [0.3, 0.1, 0.2]              # «оставить прежние»: старые даты не тронуты, новой нет — добавится
    assert list(g.merge(None, new)['kg_avg']) == [0.9]


def test_base_book_recognises_gis_table_but_not_other_csv():
    tables = {'gis_packs': pd.DataFrame([PACKS.strip().split(';'), PACK_ROW.strip().split(';')])}
    assert base_book(tables, 'gis_packs.csv') == 'таблица «База ГИС»'
    other = {'Лист1': pd.DataFrame([['well', 'date', 'q'], ['115', '2024-10-01', '5']])}
    assert base_book(other, 'x.csv') == ''
