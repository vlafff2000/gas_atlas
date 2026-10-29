"""ГИС и ГВК в Атласе: графики по скважинам и пачкам, свод и таблица изменения ГВК.
Данные — литеральные, прямо в тесте; реальных данных компании в репозитории нет."""
import pandas as pd
import pytest

from atlas.contract import Data
from atlas.domain import DatasetKind
from atlas.modules.gis import GisModule

GIS = DatasetKind.GIS_PACKS


def _frame():
    return pd.DataFrame({
        'well': ['115', '115', '115', '115', '113'],
        'date': pd.to_datetime(['2024-10-01', '2025-03-01', '2025-10-01', '2025-10-01', '2024-10-01']),
        'season': ['осень', 'весна', 'осень', 'осень', 'осень'],
        'pack': ['верхняя', 'верхняя', 'верхняя', 'нижняя', 'верхняя'],
        'gvk_abs_m': [-1000.0, -1001.0, -1003.0, -1010.0, -990.0],
        'h_eff_m': [1.5, 1.2, 1.4, 2.0, 3.0],
        'kg_avg': [0.3, 0.25, 0.28, 0.4, 0.5],
    })


def _params(**kw):
    base = {'wells': ['115', '113'], 'packs': [], 'start': '', 'end': '', 'view': 'all'}
    return {**base, **kw}


def test_one_chart_per_well_and_metric_plus_svod():
    res = GisModule().run({GIS: _frame()}, _params())
    titles = [c.id for c in res.charts]
    assert titles == ['gis-gvk-115', 'gis-h_eff-115', 'gis-kg-115', 'gis-combo-115-верхняя', 'gis-combo-115-нижняя',
                      'gis-gvk-113', 'gis-h_eff-113', 'gis-kg-113', 'gis-combo-113-верхняя',
                      'gis-pack-gvk-верхняя', 'gis-pack-gvk-нижняя', 'gis-pack-h_eff-верхняя', 'gis-pack-h_eff-нижняя',
                      'gis-pack-kg-верхняя', 'gis-pack-kg-нижняя']


def test_spring_points_are_triangles_and_lines_follow_pack():
    chart = GisModule().run({GIS: _frame()}, _params(wells=['115'])).charts[0]
    names = [(s.name, s.kind, s.symbol) for s in chart.series]
    assert ('верхняя', 'line', 'circle') in names
    assert ('верхняя: весна', 'points', 'triangle') in names
    line = next(s for s in chart.series if s.name == 'верхняя')
    assert line.y == [-1000.0, -1001.0, -1003.0] and line.group == 'верхняя'


def test_packs_and_dates_filter_the_points():
    res = GisModule().run({GIS: _frame()}, _params(wells=['115'], packs=['нижняя']))
    assert [s.name for s in res.charts[0].series] == ['нижняя']
    res = GisModule().run({GIS: _frame()}, _params(wells=['115'], start='2025-01-01', end='2025-06-30'))
    assert res.charts[0].series[1].y == [-1001.0]


def test_change_table_gives_delta_and_rate_per_pack():
    res = GisModule().run({GIS: _frame()}, _params(wells=['115']))
    row = res.tables[0].frame.set_index(['well', 'pack']).loc[('115', 'верхняя')]
    assert row['delta'] == -3.0 and row['n'] == 3
    assert round(row['rate'], 2) == -3.0                    # −3 м за один год (с 01.10.2024 по 01.10.2025)


def test_no_data_or_no_wells_gives_note():
    assert GisModule().run({}, _params()).notes[0].text.startswith('В данных нет')
    assert GisModule().run({GIS: _frame()}, _params(wells=[])).notes[0].text == 'Выберите скважины.'


def test_builder_layout_adds_gis_chart_after_main_ones():
    data = Data({GIS: _frame()})
    data.settings = {'builder_layouts': {'items': [{'id': 'g1', 'name': 'ГВК', 'layout': {
        'series': [{'dataset': 'gis_packs', 'y': 'gvk_abs_m', 'wells': ['115']}], 'title': 'ГВК 115'}}]}}
    res = GisModule().run(data, _params(wells=['115'], builder_layouts=['ГВК']))
    assert res.charts[-1].id.startswith('builder-g1')
    assert not [n for n in res.notes if n.level == 'warning']


def test_view_toggle_keeps_one_metric_or_the_svod():
    only_gvk = GisModule().run({GIS: _frame()}, _params(view='gvk')).charts
    assert [c.id for c in only_gvk] == ['gis-gvk-115', 'gis-gvk-113']
    assert len(GisModule().run({GIS: _frame()}, _params()).charts) == 15
    svod = GisModule().run({GIS: _frame()}, _params(view='svod')).charts
    assert [c.id for c in svod] == ['gis-pack-gvk-верхняя', 'gis-pack-gvk-нижняя', 'gis-pack-h_eff-верхняя',
                                    'gis-pack-h_eff-нижняя', 'gis-pack-kg-верхняя', 'gis-pack-kg-нижняя']


def test_pack_chart_puts_every_well_on_one_chart():
    svod = GisModule().run({GIS: _frame()}, _params(view='svod')).charts
    upper = next(c for c in svod if c.id == 'gis-pack-gvk-верхняя')
    assert [s.name for s in upper.series] == ['скв. 113', 'скв. 115']
    assert sum(len(s.x) for s in upper.series) == 4


def test_combo_chart_has_kg_bars_and_heff_curve():
    combo = GisModule().run({GIS: _frame()}, _params(wells=['115'], view='combo')).charts
    chart = next(c for c in combo if c.id == 'gis-combo-115-верхняя')
    assert chart.y2 is not None
    bars = [s for s in chart.series if s.kind == 'bar']
    assert [(s.name, s.axis) for s in bars] == [('Кг ср.взв', 'y')]
    assert bars[0].y == pytest.approx([0.30, 0.25, 0.28])
    lines = [s for s in chart.series if s.kind == 'line']
    assert [(s.name, s.axis) for s in lines] == [('hг эф', 'y2')]


def test_intervals_table_reaches_the_module_through_project_select():
    """Интервалы нужны виду «Σ hi × Кг» и списку сезонов: без optional проект их отбрасывал, вкладка писала «нет интервалов»."""
    assert DatasetKind.GIS_INTERVALS in GisModule.spec.optional


def test_csv_pack_table_without_season_column_does_not_crash():
    """Выгрузка gis_packs из CSV не содержит колонки «season»: графики строятся, без весенних треугольников."""
    frame = _frame().drop(columns='season')
    for view in ('gvk', 'all'):
        res = GisModule().run({GIS: frame}, _params(wells=['115'], view=view))
        assert res.charts and all(s.symbol != 'triangle' for c in res.charts for s in c.series)


def test_empty_pack_name_goes_to_separate_pack():
    frame = _frame()
    frame.loc[0, 'pack'] = None
    res = GisModule().run({GIS: frame}, _params(wells=['115']))
    assert 'без пачки' in [s.name for c in res.charts for s in c.series]


# ---- таблицы главы 5 АН (5.4–5.8) ----
INTERVALS = DatasetKind.GIS_INTERVALS


def _an_packs():
    rows = []
    for well, abs_ in (('1', [-660.7, -661.7, -660.2, -660.5]), ('4', [-667.5, -667.5, None, -667.5])):
        for (date, season), value in zip((('2024-03-30', 'весна'), ('2024-10-20', 'осень'), ('2025-03-31', 'весна'), ('2025-10-20', 'осень')), abs_):
            if value is not None:
                rows.append({'well': well, 'date': pd.Timestamp(date), 'season': season, 'pack': 'верхняя', 'gvk_abs_m': value,
                             'gvk_depth_m': 128.0 - value, 'h_eff_m': 2.5, 'kg_avg': 0.5})
    return pd.DataFrame(rows)


def _an_intervals():
    return pd.DataFrame({
        'well': ['1', '1', '1'], 'pack': ['верхняя'] * 3, 'season': ['весна', 'весна', 'осень'],
        'date': pd.to_datetime(['2024-03-30', '2024-03-30', '2024-10-20']),
        'from_m': [777.2, 778.6, 777.2], 'to_m': [778.6, 779.8, 778.6], 'kg': [0.35, 0.62, 0.35]})


def _an(**kw):
    return GisModule().run({GIS: _an_packs(), INTERVALS: _an_intervals()}, _params(view='an', **kw))


def test_an_tables_follow_report_layout_and_names():
    res = _an()
    assert [t.id for t in res.tables] == ['gis-an-5-4', 'gis-an-5-5', 'gis-an-5-6']
    comp = res.tables[1]
    assert [s for s, _ in comp.header[0]] == ['', 'отбор 2023/24 гг.', 'закачка 2024 г.', 'отбор 2024/25 гг.', 'закачка 2025 г.', '']
    assert 'выполненных в 2024/25 гг.' in comp.title
    row = comp.frame.set_index('well').loc['4']
    assert row['s2_abs'] != row['s2_abs'] and 'нет замера' in row['note']      # весна 2025: замера нет


def test_an_delta_is_depth_change_to_previous_and_same_kind():
    chg = _an().tables[2].frame.set_index('well')
    # скважина 1, как в табл. 5.6 отчёта: отбор 24/25 против отбора 23/24 — −0,5; закачка 2025 против закачки 2024 — −1,2 (ГВК поднялся)
    assert chg.loc['1', 'd_весна 2025_весна 2024'] == -0.5
    assert chg.loc['1', 'd_осень 2025_осень 2024'] == -1.2


def test_an_manual_seasons_and_base_rename_columns():
    res = _an(an_seasons=['весна 2024', 'осень 2025', 'осень 2024', 'весна 2025'][:3], an_last_two=False)
    comp = res.tables[1]
    assert [s for s, _ in comp.header[0]][1:-1] == ['отбор 2023/24 гг.', 'закачка 2024 г.', 'закачка 2025 г.']
    res = _an(an_base='осень 2024')                       # новый сезон — осень 2024: сезонов до него только три
    assert [s for s, _ in res.tables[1].header[0]][1:-1] == ['отбор 2023/24 гг.', 'закачка 2024 г.']
    assert '2023/24' not in res.tables[1].title and 'выполненных в 2024 г.' in res.tables[1].title


def test_an_without_intervals_skips_table_54_with_note():
    res = GisModule().run({GIS: _an_packs()}, _params(view='an'))
    assert [t.id for t in res.tables] == ['gis-an-5-5', 'gis-an-5-6']
    assert any('5.4' in n.text for n in res.notes)


def test_tile_view_phase_bars_kg_line_and_deltas():
    frame = _frame()
    res = GisModule().run({GIS: frame}, _params(wells=['115'], packs=['верхняя'], view='tile', seasons=[],
                                                gnt_min='0', gnt_max='3,5', kg_min='', kg_max=''))
    assert [c.id for c in res.charts] == ['gis-tile-115-верхняя']
    chart = res.charts[0]
    assert chart.y.minimum == 0 and chart.y.maximum == 3.5 and chart.y2.minimum is None
    bars = {s.name: s.y for s in chart.series if s.kind == 'bar'}
    assert bars['ГНТ — закачка'] == [1.5, None, 1.4] and bars['ГНТ — отбор'] == [None, 1.2, None]
    assert next(s for s in chart.series if s.name == 'Кг').y == pytest.approx([30.0, 25.0, 28.0])
    table = res.tables[0].frame
    assert table['d_gnt'].tolist()[1:] == pytest.approx([-0.3, 0.2]) and pd.isna(table['d_gnt'].iloc[0])


def test_tile_bad_axis_is_a_parameter_error():
    from atlas.contract import ParamError
    with pytest.raises(ParamError):
        GisModule().run({GIS: _frame()}, _params(view='tile', seasons=[], gnt_min='5', gnt_max='1', kg_min='', kg_max=''))


def test_tile_years_become_alternating_bands():
    chart = GisModule().run({GIS: _frame()}, _params(wells=['115'], packs=['верхняя'], view='tile', seasons=[],
                                                     gnt_min='', gnt_max='', kg_min='', kg_max='')).charts[0]
    assert [(b.label, b.first, b.last, b.shaded) for b in chart.bands] == [('2024', 0, 0, False), ('2025', 1, 2, True)]


def test_tile_comments_show_on_chart_and_in_table():
    from atlas.modules import gis_tiles
    data = Data({GIS: _frame()})
    data.settings = {gis_tiles.COMMENTS_KEY: {'113|верхняя|весна 2025': 'Не исследован'}}
    res = GisModule().run(data, _params(wells=['113'], packs=['верхняя'], view='tile', seasons=['осень 2024', 'весна 2025'],
                                        gnt_min='', gnt_max='', kg_min='', kg_max=''))
    note = next(s for s in res.charts[0].series if s.name == 'Комментарии')
    assert note.captions == ['Не исследован'] and note.x == ['Отбор 2024/25']
    gaps = next(t for t in res.tables if t.id == 'gis-tile-comments')
    assert gaps.frame['key'].tolist() == ['113|верхняя|весна 2025'] and gaps.action.target == 'gis-comments'


def test_tile_comments_save_and_clear():
    from atlas.modules import gis_tiles
    saved = gis_tiles.with_comments({}, {'a|b|весна 2025': {'comment': ' Технические причины '}})
    assert saved[gis_tiles.COMMENTS_KEY] == {'a|b|весна 2025': 'Технические причины'}
    assert gis_tiles.with_comments(saved, {'a|b|весна 2025': {'comment': ''}})[gis_tiles.COMMENTS_KEY] == {}


def test_gis_comments_endpoint_saves_to_project_settings(tmp_path):
    import sys
    sys.path.insert(0, 'tests/atlas')
    from starlette.testclient import TestClient

    from _wells_data import make_project
    from atlas.api import create_app
    from atlas.modules import gis_tiles
    from atlas.projects import Projects

    projects = Projects(tmp_path)
    client = TestClient(create_app(projects))
    pid = make_project(projects)
    r = client.post(f'/api/projects/{pid}/gis-comments', json={'changes': {'31|верхняя|весна 2025': {'comment': 'Не исследован'}}})
    assert r.status_code == 200, r.text
    assert projects.manifest(pid)['settings'][gis_tiles.COMMENTS_KEY] == {'31|верхняя|весна 2025': 'Не исследован'}


def test_export_all_charts_as_zip_and_sheet(tmp_path):
    import io
    import sys
    import zipfile
    sys.path.insert(0, 'tests/atlas')
    from starlette.testclient import TestClient

    from _wells_data import make_project
    from atlas.api import create_app
    from atlas.projects import Projects
    from atlas.modules.wells import SECTION_FUND

    projects = Projects(tmp_path)
    client = TestClient(create_app(projects))
    pid = make_project(projects)
    body = {'project': pid, 'params': {'section': SECTION_FUND, 'seasons_n': 2, 'wells': ['31']}, 'target': 'charts'}
    r = client.post('/api/modules/wells/export', json={**body, 'layout': 'zip'})
    assert r.status_code == 200, r.text
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert names and all(n.endswith('.png') for n in names)
    r = client.post('/api/modules/wells/export', json={**body, 'layout': 'sheet', 'cols': 3})
    assert r.status_code == 200 and r.content[:4] == b'\x89PNG'


def test_tile_keeps_measurements_outside_seasons_gray_and_does_not_crash():
    frame = pd.DataFrame({
        'well': ['115', '115'], 'date': pd.to_datetime(['2019-07-01', '2024-10-01']), 'season': ['без сезона', 'осень'],
        'pack': ['верхняя', 'верхняя'], 'gvk_abs_m': [-1000.0, -1001.0], 'h_eff_m': [2.0, 1.5], 'kg_avg': [0.3, 0.4]})
    params = _params(wells=['115'], view='tile', seasons=[], gnt_min='', gnt_max='', kg_min='', kg_max='')
    res = GisModule().run({GIS: frame}, params)
    chart = res.charts[0]
    assert chart.x.categories == ['Без сезона 2019', 'Закачка 2024']
    gray = next(s for s in chart.series if s.name == 'ГНТ — без сезона')
    assert gray.y == [2.0, None] and gray.color == '#BDBDBD'
    # сезон «без сезона 2019» выбран вручную (в том числе из вида Σ hi×Кг) — раньше это роняло расчёт
    again = GisModule().run({GIS: frame}, {**params, 'seasons': ['осень 2024', 'без сезона 2019']})
    assert again.charts[0].x.categories == ['Без сезона 2019', 'Закачка 2024']
    assert 'без сезона 2019' in GisModule().options('seasons', Data({GIS: frame}), {'view': 'tile'})


def test_an_tables_order_does_not_crash_on_unseasoned_label():
    from atlas.modules import gis_an_tables
    assert gis_an_tables.order(['осень 2024', 'без сезона 2019', 'весна 2024']) == ['без сезона 2019', 'весна 2024', 'осень 2024']


# ---- таблица 5.4 в XLSX: виды пачек, низкий Кг, объединения ----
def _an_five_four(**kw):
    """Две пачки у скважины 1: верхняя (покрышка) по сезонам 2024–2025 — в 2025 три интервала, в 2024 один;
    нижняя (нижняя пачка) — только 2024 весна. Скважина 4 без интервалов и без замера в 2025 году."""
    packs = pd.DataFrame({
        'well': ['1', '1', '1', '4'], 'date': pd.to_datetime(['2024-03-30', '2025-03-31', '2025-10-20', '2024-03-30']),
        'season': ['весна', 'весна', 'осень', 'весна'], 'pack': ['покрышка', 'покрышка', 'покрышка', 'нижняя пачка'],
        'gvk_abs_m': [-660.0, -661.0, -662.0, -667.0], 'gvk_depth_m': [120.0, 121.0, 122.0, 127.0],
        'h_eff_m': [2.5, 2.5, 2.5, 1.0], 'kg_avg': [0.5, 0.5, 0.5, 0.5]})
    intervals = pd.DataFrame({
        'well': ['1', '1', '1', '1', '1', '4'], 'pack': ['покрышка'] * 5 + ['нижняя пачка'],
        'season': ['весна', 'весна', 'весна', 'весна', 'осень', 'весна'],
        'date': pd.to_datetime(['2024-03-30', '2025-03-31', '2025-03-31', '2025-03-31', '2025-10-20', '2024-03-30']),
        'from_m': [700.0, 701.0, 703.0, 705.0, 701.0, 800.0], 'to_m': [701.0, 702.0, 704.0, 706.0, 702.0, 801.0],
        'kg': [0.10, 0.40, 0.60, 0.20, 0.30, 0.50]})
    return GisModule().run({GIS: packs, INTERVALS: intervals}, _params(view='an', **kw)).tables[0]


def test_54_intervals_sit_at_the_bottom_of_the_pack_block():
    table = _an_five_four()
    frame = table.frame
    upper = frame[frame['pack'] == 'покрышка']
    # в 2025 три интервала — по последним трём строкам блока из трёх; в 2024 один интервал — в самой нижней строке
    assert upper['s1_from'].tolist() == [701.0, 703.0, 705.0] and upper['s0_from'].iloc[-1] == 700.0
    assert pd.isna(upper['s0_from'].iloc[0])


def test_54_low_kg_cells_are_blue_and_pack_kind_colours_rows():
    table = _an_five_four()
    fills = {(st.rows[0], tuple(st.columns)): st.fill for st in table.styles if st.fill and st.columns}
    # Кг 10 % и 20 % — голубой фон у интервалов, а не у остальных
    low_rows = [r for r, st in enumerate(table.frame['s0_kg']) if st is not None and st <= 25]
    assert low_rows and all(fill == 'D3EBF7' for (row, cols), fill in fills.items() if row in low_rows)
    assert {st.font for st in table.styles if st.font} == {'1F3FBF'}
    row_fills = [st for st in table.styles if st.fill and not st.columns]
    assert {st.fill for st in row_fills} == {'FCD5B4', 'DDF0D5'}          # покрышка — светло-оранжевый, нижняя — бледно-зелёный


def test_54_not_studied_merges_season_for_well_or_pack():
    table = _an_five_four()
    marked = table.frame[table.frame.eq('не исследовалась').any(axis=1)]
    # скважина 4: весна и осень 2025 не исследовалась ни одной пачкой — объединение по её строке
    assert marked.index.tolist() == [3] and marked['well'].tolist() == ['4']
    assert {(m.first, m.last, m.columns[0]) for m in table.merges if m.first == 3} == {(3, 3, 's1_from'), (3, 3, 's2_from')}


def test_54_pack_not_studied_in_season_merges_only_its_block():
    """Скважина 1: покрышка не исследована осенью 2025, а нижняя пачка исследована — объединение только по блоку покрышки."""
    packs = pd.DataFrame({
        'well': ['1', '1', '1', '1'], 'date': pd.to_datetime(['2024-03-30', '2025-03-31', '2024-03-30', '2025-10-20']),
        'season': ['весна', 'весна', 'весна', 'осень'], 'pack': ['покрышка', 'покрышка', 'нижняя пачка', 'нижняя пачка'],
        'gvk_abs_m': [-660.0, -661.0, -667.0, -668.0], 'gvk_depth_m': [120.0, 121.0, 127.0, 128.0],
        'h_eff_m': [2.5, 2.5, 1.0, 1.0], 'kg_avg': [0.5] * 4})
    intervals = pd.DataFrame({'well': ['1'] * 4, 'pack': ['покрышка', 'покрышка', 'нижняя пачка', 'нижняя пачка'],
                              'season': ['весна', 'весна', 'весна', 'осень'],
                              'date': pd.to_datetime(['2024-03-30', '2025-03-31', '2024-03-30', '2025-10-20']),
                              'from_m': [700.0, 701.0, 800.0, 801.0], 'to_m': [701.0, 702.0, 801.0, 802.0], 'kg': [0.3] * 4})
    table = GisModule().run({GIS: packs, INTERVALS: intervals}, _params(view='an', wells=['1'])).tables[0]
    assert table.frame['pack'].tolist() == ['нижняя пачка', 'покрышка']          # блоки по алфавиту
    # нижняя не исследована весной 2025, покрышка — осенью 2025: каждая — только по своему блоку; скважина целиком — нет
    assert [(m.first, m.last, m.columns[0]) for m in table.merges] == [(0, 0, 's1_from'), (1, 1, 's2_from')]
    assert table.frame.loc[0, 's1_from'] == 'не исследовалась' and table.frame.loc[1, 's2_from'] == 'не исследовалась'


def test_54_colour_override_from_project_settings_and_bad_hex_ignored():
    from atlas.modules.gis_an_tables import palette
    assert palette({'покрышка': '#00ff00', 'нижняя пачка': 'zz'})['покрышка'] == '00FF00'
    assert palette({'нижняя пачка': 'zz'})['нижняя пачка'] == 'DDF0D5'


def test_54_xlsx_file_keeps_fills_merges_and_blue_font():
    import io
    from openpyxl import load_workbook
    from atlas import render
    content, _, _ = render.tables_file([_an_five_four()], 'Таблица 5.4')
    ws = load_workbook(io.BytesIO(content)).worksheets[0]
    cells = {c.value: c for row in ws.iter_rows() for c in row if isinstance(c.value, str) and c.value in ('покрышка', 'нижняя пачка')}
    assert cells['покрышка'].fill.fgColor.rgb.endswith('FCD5B4') and cells['нижняя пачка'].fill.fgColor.rgb.endswith('DDF0D5')
    low = [c for row in ws.iter_rows(min_row=3) for c in row if c.fill.fgColor.rgb.endswith('D3EBF7')]
    assert low and all(c.font.color.rgb.endswith('1F3FBF') for c in low)     # голубой фон у интервалов и синий шрифт строки
    assert any(c.value == 'не исследовалась' for row in ws.iter_rows() for c in row)
    missing = next(c for row in ws.iter_rows() for c in row if c.value == 'не исследовалась')
    assert any((r.min_row, r.min_col) == (missing.row, missing.column) for r in ws.merged_cells.ranges)   # объединена


def test_54_table_json_carries_the_same_styles_for_the_screen():
    from atlas.contract import Table, _table_json
    out = _table_json(_an_five_four())
    assert any(s['fill'] == 'FCD5B4' and s['rows'] for s in out['styles'])
    assert any(s['font'] == '1F3FBF' for s in out['styles'])
    assert any(m['columns'][0] == 's1_from' and m['last'] >= m['first'] for m in out['merges'])
    plain = _table_json(Table(id='x', title='t', frame=pd.DataFrame({'a': [1]})))
    assert 'styles' not in plain and 'merges' not in plain          # без оформления — прежний ответ
