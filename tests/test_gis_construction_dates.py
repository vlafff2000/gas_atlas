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
