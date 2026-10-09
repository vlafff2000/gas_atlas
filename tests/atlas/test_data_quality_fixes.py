"""Качество данных при импорте: «нет данных» −999,25, порядок даты, повторная загрузка ГДИ, потерянные исключения, журнал."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from atlas.engine.core import exclusions
from atlas.engine.core.import_rules import lost_exclusions
from atlas.engine.core.loader import date_order, dates, load_file, merge_frames, nodata, numeric


def write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding='utf-8')
    return path


def test_nodata_values_are_gaps_not_numbers():
    s = pd.Series(['-999.25', '5,5', '-999', '-9999', '-5', '0'])
    assert numeric(s).tolist()[1:2] == [5.5] and numeric(s).isna().tolist() == [True, False, True, True, False, False]
    assert nodata(s).tolist() == [True, False, True, True, False, False]
    assert numeric(s, keep_nodata=True).iloc[0] == -999.25


def test_response_row_with_nodata_pressure_keeps_the_level(tmp_path):
    """Уровень 12 при давлении −999,25: строка загружена с уровнем, давление пусто, замена записана в журнал."""
    path = write(tmp_path, 'resp.csv', 'Скважина;Дата;Горизонт;Уровень;Рпл привед.\n7;2024-03-01;A;12;-999,25\n7;2024-03-02;A;13;55\n')
    r = load_file(path, 'response', 'withdrawal', 'м³/сут', 'тыс. м³/сут')
    f = r.frames['response']
    assert r.rejected == 0 and len(f) == 2
    assert f.level.tolist() == [12.0, 13.0] and np.isnan(f.pressure.iloc[0]) and f.pressure.iloc[1] == 55.0
    assert any('нет данных' in i['Причина'] for i in r.issues)


def test_gdi_negative_rate_nodata_is_not_a_measurement(tmp_path):
    path = write(tmp_path, 'gdi.csv', 'Скважина;Дата;Q;Рпл;Рзаб\n7;2024-03-01;-999,25;80;70\n7;2024-03-02;250;80;70\n')
    r = load_file(path, 'gdi', 'withdrawal', 'м³/сут', 'тыс. м³/сут')
    assert r.frames['gdi'].q.tolist() == [250.0]       # строка с «нет данных» вместо Q отклонена, а не принята как −999,25


def test_date_order_detected_per_column():
    us = pd.Series(['12/31/2024', '01/02/2024'])
    assert date_order(us) == 'mdy'
    assert dates(us, date_order(us)).tolist() == [pd.Timestamp('2024-12-31'), pd.Timestamp('2024-01-02')]
    eu = pd.Series(['31/12/2024', '01/02/2024'])
    assert date_order(eu) == 'dmy'
    assert dates(eu, date_order(eu)).tolist() == [pd.Timestamp('2024-12-31'), pd.Timestamp('2024-02-01')]
    ambiguous = pd.Series(['01/02/2024'])
    assert date_order(ambiguous) == 'ambiguous'
    assert dates(ambiguous, 'ambiguous').iloc[0] == pd.Timestamp('2024-02-01')       # день/месяц, как и раньше
    assert date_order(pd.Series(['31/12/2024', '12/31/2024'])) == 'mixed'


def gdi_frame(**extra):
    base = dict(well=['7', '7'], date=pd.to_datetime(['2024-03-01', '2024-03-01']), method=['', ''], study=['', ''],
                q=[100.0, 200.0], dp2=[10.0, 40.0], p_res=[80.0, 80.0], p_bh=[70.0, 60.0])
    base.update(extra)
    return pd.DataFrame(base)


def test_reimport_gdi_with_new_method_column_does_not_double_points():
    old = gdi_frame()
    new = gdi_frame(method=['Режим 1', 'Режим 2'], study=['1', '1'])
    merged, removed = merge_frames(old, new, 'gdi', 'new')
    assert len(merged) == 2 and merged.method.tolist() == ['Режим 1', 'Режим 2']
    kept, _ = merge_frames(old, new, 'gdi', 'old')
    assert len(kept) == 2 and kept.method.tolist() == ['', '']


def test_different_studies_with_method_are_still_kept_apart():
    old = gdi_frame(method=['A', 'A'], study=['1', '1'])
    new = gdi_frame(method=['B', 'B'], study=['2', '2'])
    merged, _ = merge_frames(old, new, 'gdi', 'new')
    assert len(merged) == 4


def test_lost_exclusions_counted_after_value_changed():
    frame = exclusions.identify(gdi_frame(), 'gdi')
    point = frame['_point_id'].iloc[0]
    excluded = {point: {'module': 'gdi', 'id': point}}
    same = {'gdi': frame}
    assert lost_exclusions(excluded, same, same) == 0
    changed = {'gdi': gdi_frame(q=[96.0, 200.0])}
    assert lost_exclusions(excluded, changed, changed) == 1
    assert lost_exclusions({}, changed, changed) == 0


def test_issue_log_reports_omitted_entries(tmp_path):
    rows = '\n'.join(f'2024-01-01;{i};-5' for i in range(2100))
    path = write(tmp_path, 'prod.csv', 'Дата;Скважина;Q\n' + rows + '\n2024-01-02;1;100\n')
    r = load_file(path, 'production', 'withdrawal', 'м³/сут', 'тыс. м³/сут')
    assert r.rejected == 2100
    assert len(r.issues) == 2001 and 'Ещё 100' in r.issues[-1]['Причина']
