"""Выбор скважин: список из буфера обмена, пересечение групп и скважин, пользовательские пресеты, группы в ГДИ."""
from atlas import well_sets
from atlas.contract import Data
from atlas.domain import DatasetKind
from atlas.engine.core import exclusions
from atlas.engine.core.demo import well_demo_frames
from atlas.modules.gdi import GdiModule
from atlas.modules.gdi_trend import GdiTrendModule

GDI = DatasetKind.GDI
MAPPING = {'1': {'group': 'ГСП 1'}, '2': {'group': 'ГСП 1'}, '3': {'group': 'ГСП 2'}, '4': {'group': 'ГСП 2'}}


def test_parse_list_accepts_excel_column_commas_tabs_and_semicolons():
    assert well_sets.parse_list('31\n12\r\n7') == ['31', '12', '7']
    assert well_sets.parse_list('31, 12,7') == ['31', '12', '7']
    assert well_sets.parse_list('31\t12;7|8') == ['31', '12', '7', '8']
    assert well_sets.parse_list('31 12  7') == ['31', '12', '7']
    assert well_sets.parse_list('31.0\n031\n31') == ['31']           # одна скважина в разной записи
    assert well_sets.parse_list('  \n ') == []


def test_match_keeps_list_order_and_reports_missing():
    found, missing = well_sets.match(['12', '99', '7'], ['7', '12', '31'])
    assert found == ['12', '7'] and missing == ['99']


def test_scoped_without_selection_is_no_restriction():
    assert well_sets.scoped([], [], MAPPING, ['1', '2', '3']) == (None, 0)


def test_scoped_intersects_groups_with_wells_filter_and_counts_hidden():
    picked, hidden = well_sets.scoped(['1', '3'], ['ГСП 1'], MAPPING, ['1', '2', '3', '4'])
    assert picked == ['1'] and hidden == 1                            # скважина 2 из ГСП 1 скрыта фильтром
    assert well_sets.scoped([], ['ГСП 2'], MAPPING, ['1', '2', '3', '4']) == (['3', '4'], 0)
    assert well_sets.scoped(['9'], ['ГСП 1'], MAPPING, ['1', '2']) == ([], 2)


def test_user_presets_are_saved_in_project_folder(tmp_path):
    project_a, project_b = tmp_path / 'a', tmp_path / 'b'
    assert well_sets.user_presets(project_a) == []
    presets = well_sets.add_user_preset(project_a, ' Сетка ', ['31', '31', '12'])
    assert presets[0]['label'] == 'Сетка' and presets[0]['wells'] == ['31', '12']
    assert well_sets.user_presets(project_b) == []                    # в другом проекте фильтра нет
    assert well_sets.remove_user_preset(project_a, presets[0]['id']) == []


def test_user_preset_needs_name_and_wells(tmp_path):
    for name, wells in (('', ['1']), ('Пусто', [])):
        try:
            well_sets.add_user_preset(tmp_path, name, wells)
        except ValueError:
            continue
        raise AssertionError('пресет без названия или скважин не должен сохраняться')


def test_legacy_global_presets_are_imported_once_and_kept(tmp_path, monkeypatch):
    legacy, project = tmp_path / 'home', tmp_path / 'project'
    monkeypatch.setenv('PXG_HOME', str(legacy))
    well_sets.add_user_preset(legacy, 'Старый', ['5', '6'])
    assert well_sets.legacy_count() == 1
    assert well_sets.user_presets(project) == []                      # общая папка больше не видна проектам
    imported = well_sets.import_legacy(project)
    assert [(p['label'], p['wells']) for p in imported] == [('Старый', ['5', '6'])]
    assert len(well_sets.import_legacy(project)) == 1                 # повторный перенос ничего не дублирует
    assert well_sets.legacy_count() == 1                              # прежний файл не тронут


def test_gdi_groups_limit_wells_and_hide_the_rest():
    gdi = exclusions.identify(well_demo_frames()['gdi'].copy(), 'gdi')
    wells = sorted(gdi.well.astype(str).unique(), key=lambda w: int(w) if w.isdigit() else w)
    group_of = {w: ('ГСП 1' if i < 2 else 'ГСП 2') for i, w in enumerate(wells)}
    mapping = {w: {'group': g} for w, g in group_of.items()}
    module = GdiModule()
    data = Data({GDI: gdi}, {GDI: gdi}, {})
    data.mapping = mapping
    assert module.options('groups', data, {}) == ['ГСП 1', 'ГСП 2']
    picked = module.spec.coerce({'groups': ['ГСП 1'], 'wells': [wells[0], wells[-1]]})
    result = module.run(data, picked)
    notes = [n.text for n in result.notes]
    assert any('Скрыто фильтром' in t for t in notes)
    assert len(result.charts) == 1                                       # скважина из другой группы не попала


def test_gdi_trend_group_without_its_wells_gives_empty_note():
    gdi = exclusions.identify(well_demo_frames()['gdi'].copy(), 'gdi')
    data = Data({GDI: gdi}, {GDI: gdi}, {})
    data.mapping = {}
    params = GdiTrendModule().spec.coerce({'groups': ['Нет такой'], 'wells': []})
    result = GdiTrendModule().run(data, params)
    assert result.notes and 'не попало' in result.notes[0].text
