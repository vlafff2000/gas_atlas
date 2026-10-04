"""Import rules without Streamlit: shared by the 5.8 import pages and Gas Atlas 6 (atlas/imports.py).

Moved verbatim from app/ui/general_import.py and app/ui/import_editor.py; those modules re-export the names.
"""
import json
import re
import pandas as pd
from app.core import tabular
from app.core.config import MODULES
from app.core.loader import ALIASES,detect_layout,merge_frames
from app.core.well_import import REQUIRED

FIELDS={'well':'Скважина','date':'Дата','q':'Расход газа','p_res':'Пластовое давление','p_bh':'Забойное давление','dp2':'ΔP²','level':'Уровень жидкости','pressure':'Приведенное давление','horizon':'Горизонт','group':'Группа','subgroup':'Подгруппа','value':'Давление','fond':'Тип / фонд'}
FIELDS.update({f:aliases[0] for f,aliases in ALIASES.items() if f not in FIELDS})
MODULE_CHOICES=['auto','production','gdi','response','object_pressure','operations','water','bottom','construction','plan','groups','subgroups']

TYPES={'auto':'Автоопределение','groups':'Группы (в том числе без заголовков)','subgroups':'Подгруппы (в том числе без заголовков)'}
TEXT_TYPES=['xlsx','xls','xlsm','ods','csv','tsv','txt','dat']
PRESSURE_WORDS=(('факт','hist','fact'),('модел','gdm','model'))
PSI_TO_KGF=10.197162129779

def type_label(value):
    return TYPES.get(value) or MODULES.get(value,value)

def is_pressure_book(names):
    low=[n.lower() for n in names]
    return any(any(w in n for w in PRESSURE_WORDS[0]) for n in low) and any(any(w in n for w in PRESSURE_WORDS[1]) for n in low)

def auto_spec(raw,module):
    """Same structure the detailed editor produces, built from the detected layout."""
    head=raw.values.tolist();layout=detect_layout(head,module)
    if layout['module'] is None:raise ValueError('Колонки не подходят для типа «'+type_label(module)+'»')
    required={**REQUIRED,'production':{'well','date','q'},'gdi':{'well','date','q'},'response':{'well','date','horizon'},'object_pressure':{'date','pressure'},'plan':{'group','date','plan_volume'},'groups':{'well'}}.get(layout['module'],set())
    missing=required-layout['mapping'].keys()
    if not layout['wide'] and missing:raise ValueError('Не найдены колонки: '+', '.join(FIELDS.get(f,f) for f in sorted(missing)))
    if layout['module']=='gdi' and not ('dp2' in layout['mapping'] or {'p_res','p_bh'}<=layout['mapping'].keys()):raise ValueError('Для ГДИ нужны Рпл и Рзаб либо ΔP²')
    header=layout['header'];columns=range(raw.shape[1])
    labels=[('' if pd.isna(v) else str(v).strip()) for v in (raw.iloc[header] if header>=0 else ['']*raw.shape[1])]
    mapping=dict(layout['mapping']);datecol=mapping.get('date',0)
    return {'enabled':True,'valid':True,'module':layout['module'],'header':int(header),'mapping':mapping,'wide':bool(layout['wide']),'datecol':datecol,
            'wellcols':[i for i in columns if i!=datecol and labels[i] and not labels[i].startswith('Unnamed:')] if layout['wide'] else [],
            'names':{str(i):v for i,v in enumerate(labels)},'fond_pairs':[]}

def describe(raw,module):
    try:
        layout=detect_layout(raw.values.tolist(),module)
    except Exception:return None,''
    if layout['module'] is None:return None,''
    fields=', '.join(FIELDS.get(f,f) for f in layout['mapping']) if not layout['wide'] else 'матрица: группы × месяцы' if layout['module']=='plan' else 'матрица: даты × скважины'
    return layout['module'],fields

def to_kgf(frames,factor=PSI_TO_KGF):
    """Pressures given in MPa -> kgf/cm2, in place (pressures, ΔP² and DB coefficients)."""
    if 'gdi' in frames:
        g=frames['gdi']
        for col in ('p_res','p_bh'):
            if col in g:g[col]*=factor
        for col in ('dp2','a_db','b_db'):
            if col in g:g[col]*=factor**2
    if 'response' in frames and 'pressure' in frames['response']:frames['response']['pressure']*=factor
    if 'object_pressure' in frames:frames['object_pressure']['pressure']*=factor
    if 'operations' in frames:
        for col in ('p_res','p_bh','p_wellhead','p_line'):
            if col in frames['operations']:frames['operations'][col]*=factor
    return frames

def merge_import(raw_frames,groups,parsed,policy):
    """Checked import merged into the project tables and group assignments: (frames, groups, removed duplicates)."""
    updated=dict(raw_frames);groups=dict(groups);duplicates=0
    for module,frame in parsed.items():
        if module=='groups':
            for row in frame.itertuples():
                change={}
                if row.group and row.group!='Без группы':change['group']=row.group
                if row.subgroup:change['subgroup']=row.subgroup
                groups.setdefault(row.well,{}).update(change)
        else:
            updated[module],count=merge_frames(updated.get(module),frame,module,policy);duplicates+=count
    return updated,groups,duplicates

def pressure_layout(raw):
    from app.modules import pressure_match as pm
    for i in range(min(30,len(raw))):
        labels=list(raw.iloc[i]);table=tabular.headed(raw,i);cfg=pm.detect_columns(table)
        recognized=any(re.search(pm.ALIASES['date'],str(v),re.I) for v in labels)
        if recognized or i+1<len(raw) and pd.notna(pm.dates(pd.Series([raw.iloc[i+1,0]])).iloc[0]):
            mapping={k:labels.index(cfg[k]) for k in ('date','well','value') if cfg[k] is not None and cfg[k] in labels}
            mapping.setdefault('date',0)
            return {'header':i,'mapping':mapping,'wide':cfg['format']=='wide'}
    return {'header':0,'mapping':{'date':0},'wide':True}

def pressure_table(raw,spec):
    if not spec.get('enabled') or not spec.get('valid',True):raise ValueError('Лист отключен или сопоставление колонок некорректно.')
    data=tabular.headed(raw,spec['header']);mapping=spec['mapping'];offset=spec['header']+2
    if spec['wide']:
        if 'date' not in mapping:raise ValueError('Выберите колонку даты.')
        datecol=mapping['date'];parts=[]
        for col in spec['wellcols']:
            parts.append(pd.DataFrame({'Дата':data.iloc[:,datecol],'Скважина':spec['names'][str(col)],'Давление':data.iloc[:,col],'Строка источника':range(offset,offset+len(data))}))
        data=pd.concat(parts,ignore_index=True)
        cfg={'format':'long','date':'Дата','well':'Скважина','value':'Давление','row_offset':offset,'row_column':'Строка источника'}
    else:
        if not {'date','well','value'}<=mapping.keys():raise ValueError('Назначьте дату, скважину и давление.')
        data=data.iloc[:,[mapping[f] for f in ('date','well','value')]].copy();data.columns=['Дата','Скважина','Давление'];cfg={'format':'long','date':'Дата','well':'Скважина','value':'Давление','row_offset':offset}
    cfg['source_signature']=json.dumps(spec,ensure_ascii=False,sort_keys=True)+str(raw.attrs.get('source_options',''))
    return data,cfg

def fonds_table(raw,spec):
    from app.modules.pressure_match import normalize_fonds
    if not spec.get('enabled'):return {}
    if not spec.get('valid',True):raise ValueError('Исправьте колонки фонда.')
    rows=tabular.headed(raw,spec['header']);result={}
    for wc,fc in spec['fond_pairs']:
        pair=rows.iloc[:,[wc,fc]].copy();pair.columns=['Скважина','Тип'];result.update(normalize_fonds(pair))
    return result

def parse_pressure_book(content,name,options,tables=None):
    """``tables``: all rows of every sheet (tabular.read_content); read here when not given."""
    from app.modules import pressure_match as pm
    from app.core.loader import ImportResult
    raw=tables if tables is not None else tabular.read_content(content,name,None,options['encoding'],options['delimiter'])[1];specs=options['sheets']
    fact,cfg=pressure_table(raw[options['fact']],specs[options['fact']]);fact=pm.normalize(fact,cfg)
    fonds={};parts=[];notes=[]
    for sheet in options['fonds']:fonds.update(fonds_table(raw[sheet],specs[sheet]))
    for sheet in options['models']:
        model,cfg=pressure_table(raw[sheet],specs[sheet]);data,diagnostics=pm.pair(fact,pm.normalize(model,cfg),options['object'],sheet,fonds,options.get('duplicate','first'))
        data['file']=name;data['sheet']=options['fact'];parts.append(data);notes+=diagnostics
    if not parts:raise ValueError('Выберите хотя бы один лист модели для кроссплота.')
    data=pd.concat(parts,ignore_index=True)
    if data.empty:raise ValueError('Не распознаны даты и скважины. Проверьте шапку.')
    result=ImportResult(frames={'pressure_match':data},counts={'pressure_match':len(data)})
    for note in notes:result.issue(name,options['fact'],0,str(note),'предупреждение')
    return result
