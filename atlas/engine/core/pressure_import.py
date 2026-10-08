"""Quick bulk import for the pressure crossplot, without Streamlit: sheet roles, layouts, pairing.

Moved verbatim from app/ui/pressure_quick_import.py (which re-exports the names); also used by Gas Atlas 6.
"""
import re
from pathlib import Path
import numpy as np
import pandas as pd
from atlas.engine.core import tabular,profiles
from atlas.engine.modules import pressure_match as pm
from atlas.engine.core.import_rules import pressure_layout,pressure_table,fonds_table

FACT,MODEL,FOND,SKIP='Факт','Модель','Фонд','Пропустить'
ROLES=[FACT,MODEL,FOND,SKIP]
FACT_RE=r'факт|hist|fact|замер|измер'
MODEL_RE=r'модел|gdm|model|сценар|scenario|прогноз|расч|calc'
FOND_RE=r'фонд|fond'
SKIP_RE=r'инструкц|readme|help|описани|info'
ROLE_WORDS=re.compile(r'(факт\w*|fact\w*|hist\w*|модел\w*|model\w*|gdm|сценар\w*|scenario\w*)',re.I)
DUPLICATES={'first':'Первая запись (как в Python-скрипте)','last':'Последняя запись','mean':'Среднее значение','error':'Остановить импорт'}
TEXT_TYPES=['xlsx','xls','xlsm','ods','csv','tsv','txt','dat']
MAX_PARALLEL_NOTE=8

def is_binary_book(content):
    return content.startswith((b'PK',b'\xd0\xcf\x11\xe0'))

def _labels(preview,header):
    return ['' if pd.isna(v) else str(v).strip() for v in preview.iloc[header]]

def auto_spec(preview,fonds=False):
    """Same structure that import_editor.sheet_editor returns, built from detected defaults."""
    columns=range(preview.shape[1])
    remembered=profiles.find(preview,'pressure_fond' if fonds else 'pressure')
    if remembered:return remembered
    if fonds:
        labels=_labels(preview,0)
        wells=[j for j,v in enumerate(labels) if re.search(r'скваж|well|^скв',v,re.I)]
        types=[j for j,v in enumerate(labels) if re.search(r'тип|type|фонд|fond',v,re.I)]
        if not wells or not types:raise ValueError('Не найдены колонки «Скважина» и «Тип / фонд».')
        return {'enabled':True,'valid':True,'module':'pressure_match','header':0,'mapping':{},'wide':False,'datecol':0,'wellcols':[],
                'names':{str(i):v for i,v in enumerate(labels)},'fond_pairs':[[w,t] for w,t in zip(wells,types)]}
    layout=pressure_layout(preview);header=layout['header'];labels=_labels(preview,header);names={str(i):v for i,v in enumerate(labels)}
    mapping=dict(layout['mapping']);wide=bool(layout['wide'])
    if wide:
        datecol=mapping.get('date',0);wellcols=[i for i in columns if i!=datecol and labels[i] and not labels[i].startswith('Unnamed:')]
        if not wellcols:raise ValueError('Не найдены колонки скважин.')
    else:
        if not {'date','well','value'}<=mapping.keys():raise ValueError('Не распознаны колонки даты, скважины и давления.')
        wellcols=[]
    return {'enabled':True,'valid':True,'module':'pressure_match','header':int(header),'mapping':mapping,'wide':wide,'datecol':mapping.get('date',0),
            'wellcols':wellcols,'names':names,'fond_pairs':[]}

def guess_role(sheet,filename,sheets,batch_has_fact):
    low=sheet.lower()
    if re.search(SKIP_RE,low):return SKIP,True
    if re.search(FOND_RE,low):return FOND,True
    if re.search(FACT_RE,low):return FACT,True
    if re.search(MODEL_RE,low):return MODEL,True
    stem=Path(filename).stem.lower()
    if len(sheets)==1:
        if re.search(FACT_RE,stem):return FACT,True
        if re.search(MODEL_RE,stem):return MODEL,True
        return (MODEL if batch_has_fact else FACT),False
    return None,False

def guess_object(filename,multi,default):
    stem=Path(filename).stem
    if multi:return stem
    rest=re.sub(r'[\s_\-.()]+',' ',ROLE_WORDS.sub('',stem)).strip()
    return default if not rest or rest.isdigit() else rest

def guess_scenario(filename,sheet,multi,obj):
    if multi:return sheet
    stem=Path(filename).stem;rest=re.sub(r'^[\s_\-.()]+|[\s_\-.()]+$','',stem.replace(obj,'',1)) if obj in stem else ''
    return rest or stem

def parse_file(name,content,encoding='auto',delimiter='auto'):
    """Read one file once; return per-sheet records with detected layout and normalized rows."""
    fmt,tables=tabular.read_content(content,name,None,encoding,delimiter)
    sheets={}
    for sheet,raw in tables.items():
        record={'raw':raw,'spec':None,'norm':None,'fonds':None,'error':None,'fond_spec':None}
        if raw.empty or raw.shape[1]<2:record['error']='Пустой лист'
        else:
            preview=raw.head(31)
            try:
                spec=auto_spec(preview);record['spec']=spec;record['norm']=_normalize(raw,spec)
            except Exception as error:record['error']=str(error)
            try:record['fond_spec']=auto_spec(preview,fonds=True)
            except Exception:pass
        sheets[sheet]=record
    return {'format':fmt,'sheets':sheets,'encoding':encoding,'delimiter':delimiter}

def _normalize(raw,spec):
    data,cfg=pressure_table(raw,spec);norm=pm.normalize(data,cfg)
    if norm.empty:raise ValueError('Нет строк с распознанными датой и скважиной.')
    return norm

def refresh(record,spec):
    record['spec']=spec;record['error']=None
    try:record['norm']=_normalize(record['raw'],spec)
    except Exception as error:record['norm']=None;record['error']=str(error)

def describe(record):
    n=record['norm']
    if n is None:return 0,0,'—','—'
    valid=int(n.value.notna().sum())
    return valid,n.well.nunique(),str(n.date.min().date())+' … '+str(n.date.max().date()),'матрица' if record['spec']['wide'] else 'строки'

def build_rows(files,cache,choices,project_name):
    """Deterministic table of every sheet of every file with guessed roles; user choices override guesses."""
    rows=[];batch_has_fact=any(re.search(FACT_RE,sheet.lower()) for sha in files for sheet in cache[sha]['sheets'])
    for sha,(name,_) in files.items():
        parsed=cache[sha];sheets=list(parsed['sheets']);multi=len(sheets)>1
        guesses={s:guess_role(s,name,sheets,batch_has_fact) for s in sheets}
        # Sheets with unrecognized names: the first readable one is the fact unless the file already has one.
        has_fact=any(r==FACT for r,_ in guesses.values());first=True
        for s,(role,_) in list(guesses.items()):
            if role is None:
                if parsed['sheets'][s]['error']:guesses[s]=(MODEL,False)
                else:guesses[s]=(FACT if first and not has_fact else MODEL,False);first=False
        for s in sheets:
            record=parsed['sheets'][s];role,sure=guesses[s];c=choices.get((sha,s),{})
            role=c.get('role',role)
            valid,wells,period,layout=describe(record)
            if role==FOND:status='OK' if record['fond_spec'] else 'Ошибка: нет колонок «Скважина» и «Тип / фонд»';usable=bool(record['fond_spec'])
            elif record['error']:status='Ошибка: '+record['error'];usable=False
            else:status='OK' if sure or 'role' in c else 'Роль определена по порядку листов — проверьте';usable=role!=SKIP
            use=bool(c.get('use',usable and guesses[s][0]!=SKIP))
            obj=c.get('object') or guess_object(name,multi,project_name)
            scenario=c.get('scenario') or guess_scenario(name,s,multi,obj)
            rows.append({'Исп.':use,'Файл':name,'Лист':s,'Роль':role,'Объект':obj,'Сценарий':scenario if role==MODEL else '','Общая':role==FACT and bool(c.get('shared')),'Значений':valid,'Скважин':wells,'Период':period,'Структура':layout,'Статус':status,'_sha':sha})
    return rows

def stored_fact(existing,obj):
    """History of one object already in the project, in the shape of a normalized fact table (None when there is none)."""
    if existing is None or existing.empty:return None
    d=existing[(existing.object==obj)&existing.fact.notna()]
    if d.empty:return None
    d=d.drop_duplicates(['well','date']);row=d['_row'] if '_row' in d else pd.Series(np.arange(len(d))+2,index=d.index)
    return pd.DataFrame({'date':d.date.values,'well':d.well.values,'value':d.fact.values,'_row':row.values})

def assemble(rows,cache,duplicate,existing=None):
    """Pair fact and model rows per object. Returns (data,notes,errors,warnings,summary).

    A fact row flagged ``Общая`` is the one history for every object of the batch that has no fact of its own;
    an object with models but no fact at all takes the history already stored in the project (``existing``)."""
    notes=[];errors=[];warnings=[];parts=[];groups={};shared=[]
    for r in rows:
        if not r['Исп.'] or r['Роль']==SKIP:continue
        if r['Роль']==FACT and r.get('Общая'):shared.append(r);continue
        groups.setdefault(r['Объект'].strip() or 'Объект',[]).append(r)
    if not groups and not shared:raise ValueError('Не выбран ни один лист.')
    shared_facts=[]
    for r in shared:
        record=cache[r['_sha']]['sheets'][r['Лист']]
        if record['norm'] is None:errors.append(r['Файл']+' / '+r['Лист']+': '+str(record['error']))
        else:shared_facts.append(record['norm'])
    for obj,items in groups.items():
        facts=[];models=[];fonds={}
        for r in items:
            record=cache[r['_sha']]['sheets'][r['Лист']]
            if r['Роль']==FOND:
                if not record['fond_spec']:errors.append(r['Файл']+' / '+r['Лист']+': нет колонок фонда');continue
                fonds.update(fonds_table(record['raw'],record['fond_spec']));continue
            if record['norm'] is None:errors.append(r['Файл']+' / '+r['Лист']+': '+str(record['error']));continue
            if r['Роль']==FACT:facts.append(record['norm'])
            else:models.append((r,record['norm']))
        if not models:warnings.append('Объект «'+obj+'»: нет моделей, объект пропущен.');continue
        if not facts and shared_facts:facts=shared_facts
        if not facts:
            kept=stored_fact(existing,obj)
            if kept is not None:facts=[kept];warnings.append('Объект «'+obj+'»: история взята из проекта — сохраняйте способом «Добавить сценарии», чтобы не потерять прежние сценарии.')
        if not facts:errors.append('Объект «'+obj+'»: не выбран лист или файл с фактом (или отметьте факт как общую историю).');continue
        fact=pd.concat(facts,ignore_index=True) if len(facts)>1 else facts[0]
        seen={}
        for r,model in models:
            label=(r['Сценарий'] or '').strip() or r['Лист']
            seen.setdefault(label,[]).append((r,model))
        for label,entries in seen.items():
            if len(entries)>1:
                warnings.append('Объект «'+obj+'»: сценарий «'+label+'» встречается '+str(len(entries))+' раза — к названию добавлено имя файла.')
        for label,entries in seen.items():
            for r,model in entries:
                scenario=label if len(entries)==1 else label+' ('+Path(r['Файл']).stem+')'
                data,found=pm.pair(fact,model,obj,scenario,fonds,duplicate);data['file']=r['Файл'];data['sheet']=r['Лист'];parts.append(data);notes.extend(found)
    if errors:return None,notes,errors,warnings,None
    if not parts:raise ValueError('Нет ни одной пары «факт — модель». Проверьте роли листов.')
    result=pd.concat(parts,ignore_index=True)
    if result.empty:raise ValueError('Нет записей с распознанными датами и скважинами.')
    if result.duplicated(['object','scenario','well','date']).any():errors.append('Повторяются объект / сценарий. Задайте уникальные названия.')
    complete=result[result.fact.notna()&result.model.notna()]
    summary=pd.DataFrame([{'Объект':o,'Сценарий':s,'Пар (факт+модель)':int(len(complete[(complete.object==o)&(complete.scenario==s)])),'Неполных':int(len(g)-len(complete[(complete.object==o)&(complete.scenario==s)])),'Скважин':g.well.nunique(),
        'Период':str(g.date.min().date())+' … '+str(g.date.max().date())} for (o,s),g in result.groupby(['object','scenario'],sort=False)])
    return result,notes,errors,warnings,summary
