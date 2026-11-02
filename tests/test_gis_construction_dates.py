"""«ГИС и ГВК», схема скважины: конструкция по датам — последняя по умолчанию, прежние рядом, забой не позже даты, пометка «Ресурс»."""
import pandas as pd

from atlas.modules import gis_well


def cons():
    rows = []
    for date, ek, res in (('2013-05-29', 784.0, 'Да'), ('2016-06-10', 790.0, '')):
        rows += [{'well': '500', 'date': pd.Timestamp(date), 'element': 'Эксплуатационная колонна', 'top_m': 0.0, 'bottom_m': ek, 'resource': res},
                 {'well': '500', 'date': pd.Timestamp(date), 'element': 'Фильтр', 'top_m': 785.0, 'bottom_m': 795.0, 'resource': res}]
    return pd.DataFrame(rows)


def bottoms():
    return pd.DataFrame({'well': ['500', '500'], 'date': [pd.Timestamp('2013-05-29'), pd.Timestamp('2016-06-10')], 'bottom_m': [796.4, 798.0]})


def items(chart):
    return {i['label']: i for i in chart.figure.data['scheme']['items']}


def test_latest_by_default_and_old_snapshot():
    c = cons()
    new = gis_well.construction_chart('500', c, bottoms(), None, False)
    old = gis_well.construction_chart('500', c, bottoms(), None, False, date=pd.Timestamp('2013-05-29'))
    assert new.figure.data['date'] == '10.06.2016' and old.figure.data['date'] == '29.05.2013'
    assert items(new)['Эксплуатационная колонна']['bottom'] == 790.0 and items(old)['Эксплуатационная колонна']['bottom'] == 784.0
    assert new.figure.data['scheme']['bottom_m'] == 798.0 and old.figure.data['scheme']['bottom_m'] == 796.4     # у прежнего — забой на его дату
    assert old.figure.data['resource'] and '«Ресурс»' in old.title and not new.figure.data['resource']
    assert new.id != old.id


def test_compare_with_other_file():
    """Даты не сопоставляются: у каждой скважины берётся самая свежая конструкция каждой базы, ранние не проверяются."""
    from atlas.modules import gis_cons_compare as cc
    other = cons().copy()
    other.loc[(other['date'] == pd.Timestamp('2016-06-10')) & (other['element'] == 'Фильтр'), 'bottom_m'] = 799.0
    other.loc[other['date'] == pd.Timestamp('2013-05-29'), 'bottom_m'] = 1.0           # старый снимок файла не проверяется
    d = cc.compare(cons(), other)
    assert list(d['Элемент']) == ['Фильтр'] and d.iloc[0]['Расхождение'] == 'глубины различаются'
    assert d.iloc[0]['Дата в проекте'] == d.iloc[0]['Дата в файле'] == '10.06.2016'
    svod = cons()[cons()['date'] == pd.Timestamp('2013-05-29')].copy()
    svod['date'] = pd.Timestamp('2000-01-01')                                          # свод: дата ничего не значит
    d2 = cc.compare(svod, cons())
    assert set(d2['Расхождение']) == {'глубины различаются'} and set(d2['Дата в проекте']) == {'01.01.2000'} and set(d2['Дата в файле']) == {'10.06.2016'}
    assert cc.compare(cons(), cons()).empty and cc.compare(cons(), other, wells=['999']).empty


def test_view_cons_compare(tmp_path):
    from atlas.domain import DatasetKind
    from atlas.modules.gis import GisModule
    other = cons().copy()
    other.loc[other['element'] == 'Фильтр', 'bottom_m'] = 800.0
    cols = {'well': 'Скважина', 'date': 'Дата конструкции', 'element': 'Элемент', 'top_m': 'Верх интервала, м', 'bottom_m': 'Низ интервала, м'}
    path = tmp_path / 'о.xlsx'
    other.rename(columns=cols)[list(cols.values())].to_excel(path, sheet_name='Конструкция', index=False)
    res = GisModule.run_cons_compare({DatasetKind.CONSTRUCTION: cons()}, {'cons_other': str(path), 'cons_tol': 0.5, 'wells': []})
    assert len(res.tables) == 1 and set(res.tables[0].frame['Расхождение']) == {'глубины различаются'} and len(res.tables[0].frame) == 1
    assert 'решает инженер' in res.notes[0].text


def test_dates_only_for_selected_wells_and_result_is_json():
    """Даты в списке — только выбранных скважин (параметр зависит от «Скважины»); результат сериализуется в JSON (раньше numpy.bool_ давал 500)."""
    import json
    from atlas.domain import DatasetKind
    from atlas.modules.gis import GisModule
    c = pd.concat([cons(), cons().assign(well='600', date=pd.Timestamp('2020-02-02'))])
    mod = GisModule()
    spec = next(p for p in mod.spec.params if p.name == 'cons_dates')
    assert 'wells' in spec.depends
    data = {DatasetKind.CONSTRUCTION: c}
    assert mod.options('cons_dates', data, {'wells': ['600']}) == ['02.02.2020']
    assert mod.options('cons_dates', data, {'wells': ['500']}) == ['10.06.2016', '29.05.2013']
    chart = gis_well.construction_chart('500', c, bottoms(), None, False)
    json.dumps(chart.figure.data['resource'])
    for date in (None, pd.Timestamp('2013-05-29')):
        json.dumps(gis_well.construction_chart('500', c, bottoms(), None, False, date=date).figure.data, default=str)
        assert type(gis_well.construction_chart('500', c, bottoms(), None, False, date=date).figure.data['resource']) is bool
