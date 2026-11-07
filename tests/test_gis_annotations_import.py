"""База ГИС: аннотации отчётов (gis_annotations) читаются в проект Атласа. Файлы литеральные, реальных данных нет."""
import io

import pandas as pd
import pytest

from atlas.engine.core import gis_import as g

HEAD = 'well;date;pack;kind;text;from_m;to_m;file;source;confidence\n'


def _csv(text: str) -> bytes:
    return ('﻿' + text).encode('utf-8')


def test_detect_annotations_by_header():
    assert g.detect(HEAD.strip().split(';')) == 'gis_annotations'


def test_read_csv_keeps_rows_without_pack_and_drops_non_well():
    text = (HEAD + '108;2023-12-08;;ГВК не достигнут;вид;;;f;текст отчёта;средняя\n'
            '109;2023-12-08;А;Заглинизированный прослой;т;610,5;612,0;f;таблица;высокая\n'
            'АЛЬТИТУДА;2023-12-08;;Примечание;т;;;f;Excel;средняя\n')
    table, frame, warnings = g.read('gis_annotations.csv', _csv(text))
    assert table == 'gis_annotations' and frame['well'].tolist() == ['108', '109']
    assert frame.loc[1, 'from_m'] == pytest.approx(610.5) and any('слово' in w for w in warnings)


def test_book_sheet_annotations_keeps_empty_pack():
    frame = pd.DataFrame({'Скважина': ['5'], 'Дата': ['08.12.2023'], 'Пачка': [None], 'Вид': ['Ремонт'], 'Текст': ['х']})
    buf = io.BytesIO()
    with pd.ExcelWriter(buf) as xw:
        frame.to_excel(xw, sheet_name='Аннотации', index=False)
    parts = g.read_all('БД_ГИС_единая.xlsx', buf.getvalue())
    assert [p[0] for p in parts] == ['gis_annotations'] and len(parts[0][1]) == 1
