"""База ГИС: термобарика и заполнение ствола из отчётов (БД ГИС) читаются в проект Атласа.
Файлы литеральные, реальных данных компании в репозитории нет."""
import io

import pandas as pd
import pytest

from atlas.engine.core import gis_import as g

THERMO = 'well;date;depth_m;depth_abs_m;depth_kind;depth_note;temp_c;pressure_raw;pressure_unit;pressure_kgs;file;source;confidence;basis\n'
FILLING = 'well;date;regime;from_m;to_m;density_min;density_max;fill_raw;fill;level_m;level_raw;origin;file;source;confidence;basis\n'


def _csv(text: str) -> bytes:
    return ('﻿' + text).encode('utf-8')


def test_detect_thermobaric_and_filling_by_header():
    assert g.detect(THERMO.strip().split(';')) == 'gis_thermobaric'
    assert g.detect(FILLING.strip().split(';')) == 'gis_filling'


def test_read_thermobaric_csv_drops_non_well_rows_and_keeps_numbers():
    text = (THERMO + '108;2023-12-08;600,0;-472,1;;;16,2;62,8;ат;62,8;f;т;средняя;\n'
            'АЛЬТИТУДА;2022-01-01;20,0;;;;9,2;;;;f;текст;средняя;\n'
            '109;;800,0;-676,0;;;;81,6;ат;81,6;f;т;средняя;\n')
    table, frame, warnings = g.read('gis_thermobaric.csv', _csv(text))
    assert table == 'gis_thermobaric'
    assert frame['well'].tolist() == ['108'] and frame.loc[0, 'pressure_kgs'] == pytest.approx(62.8)
    assert frame.loc[0, 'depth_abs_m'] == pytest.approx(-472.1)
    assert any('слово' in w and 'АЛЬТИТУДА' in w for w in warnings) and any('без скважины или даты' in w for w in warnings)


def test_read_filling_csv_numbers_density():
    text = FILLING + '14;2022-10-05;;500,0;800,0;1,05;1,1;Скважина заполнена жидкостью;жидкость;;;таблица;f;т;высокая;\n'
    table, frame, _ = g.read('gis_filling.csv', _csv(text))
    assert table == 'gis_filling' and frame.loc[0, 'density_min'] == pytest.approx(1.05) and frame.loc[0, 'fill'] == 'жидкость'


def test_book_sheets_with_russian_headers_are_read_as_text_numbers():
    thermo = pd.DataFrame({'Скважина': ['108'], 'Дата': ['08.12.2023'], 'Глубина, м': ['600.0'], 'Глубина а.о., м': [-472.1],
                           'Давление, кгс/см²': ['62.8'], 'Единица давления': ['ат']})
    filling = pd.DataFrame({'Скважина': ['108'], 'Дата': ['08.12.2023'], 'От, м': [500], 'До, м': [800],
                            'Плотность от, г/см³': [1.0], 'Заполнение': ['вода']})
    buf = io.BytesIO()
    with pd.ExcelWriter(buf) as xw:
        thermo.to_excel(xw, sheet_name='Термобарика', index=False)
        filling.to_excel(xw, sheet_name='Заполнение ствола', index=False)
    parts = {kind: frame for kind, frame, _ in g.read_all('БД.xlsx', buf.getvalue())}
    assert set(parts) == {'gis_thermobaric', 'gis_filling'}
    assert parts['gis_thermobaric'].loc[0, 'pressure_kgs'] == pytest.approx(62.8)
    assert parts['gis_thermobaric'].loc[0, 'date'] == pd.Timestamp('2023-12-08')
    assert parts['gis_filling'].loc[0, 'density_min'] == pytest.approx(1.0)
