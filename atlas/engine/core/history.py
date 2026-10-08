"""Auditable before/after filter states and GDI parameters."""
import copy
import pandas as pd
from . import exclusions
from atlas.engine.modules import gdi


def filter_details(raw,before,after,added,removed):
    old=before.get('excluded_points',{});new=after.get('excluded_points',{})
    entries=list(added)+[old[x] for x in removed if x in old]
    wells={x.get('well') for x in entries if x and x.get('module')=='gdi'}
    details={'before_exclusions':copy.deepcopy(old),'after_exclusions':copy.deepcopy(new),
             'added_ids':[x['id'] for x in added if x],'removed_ids':list(removed),'gdi_before':[],'gdi_after':[]}
    if wells and 'gdi' in raw:
        from .performance import select_wells
        source={'gdi':select_wells(raw['gdi'],wells)}
        for label,settings in [('gdi_before',before),('gdi_after',after)]:
            d=exclusions.apply(source,settings)['gdi']
            details[label]=gdi.analyze(d,settings.get('r2_threshold',.95)).to_dict('records')
    return details


def comparison(details):
    frames=[]
    for field,label in [('gdi_before','До'),('gdi_after','После')]:
        for row in details.get(field,[]):
            frames.append({'Состояние':label,'Скважина':row['well'],'Дата':row['date'],
                'Метод':row.get('method',''),'Исследование':row.get('study',''),
                'a':row.get('a_calc'),'b':row.get('b_calc'),'R²':row.get('r2_calc'),
                'Qmax':row.get('q_observed'),'Точек':row.get('points')})
    return pd.DataFrame(frames)
