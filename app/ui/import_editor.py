"""One import editor for all tabular modules. No nested expanders."""
import hashlib
import json
import re
from pathlib import Path
import pandas as pd
import streamlit as st
from app.core import tabular
from app.core.loader import ALIASES,detect_layout,column_map
from app.core.config import MODULES
from app.core.well_import import REQUIRED

from app.core.import_rules import FIELDS,MODULE_CHOICES,pressure_layout,pressure_table,fonds_table
from app.core import import_rules

@st.cache_data(show_spinner=False,max_entries=64)
def samples(content,name,encoding='auto',delimiter='auto'):
    return tabular.read_content(content,name,31,encoding,delimiter)

@st.cache_data(show_spinner=False,max_entries=48)
def full_tables(content,name,encoding='auto',delimiter='auto'):
    return tabular.read_content(content,name,None,encoding,delimiter)[1]

def text_options(content,name,prefix):
    encoding=delimiter='auto'
    if not content.startswith((b'PK',b'\xd0\xcf\x11\xe0')):
        a,b=st.columns(2)
        encoding=a.selectbox('Кодировка · '+name,['auto','utf-8-sig','cp1251','utf-16','utf-16-le','utf-16-be'],key=prefix+'_encoding',format_func=lambda v:'Автоопределение' if v=='auto' else v)
        delimiter=b.selectbox('Разделитель · '+name,['auto','\t',',',';','|','whitespace'],key=prefix+'_delimiter',format_func=lambda v:{'auto':'Автоопределение','\t':'Табуляция','; ':'Точка с запятой и пробел',';':'Точка с запятой',',':'Запятая','|':'Вертикальная черта','whitespace':'Пробелы'}.get(v,v))
        if delimiter=='; ':delimiter=';'
    return encoding,delimiter

def sheet_editor(raw,sheet,prefix,module='auto',pressure=False,fonds=False):
    st.markdown('**Лист: '+sheet+'**')
    if raw.empty or raw.shape[1]==0:st.info('Пустой лист');return {'enabled':False}
    preview=raw.fillna('').astype(str);preview.columns=['Колонка '+str(j+1) for j in range(raw.shape[1])];preview.index=range(1,len(raw)+1)
    st.caption('Исходный файл: первые 31 строка; номера строк слева соответствуют файлу. Значения не изменяются.')
    st.dataframe(preview,use_container_width=True,height=230)
    enabled=st.checkbox('Использовать лист · '+sheet,value=sheet!='Инструкция',key=prefix+'_enabled')
    if not enabled:return {'enabled':False}
    try:layout={'header':0,'mapping':{},'wide':False} if fonds else pressure_layout(raw) if pressure else detect_layout(raw.values.tolist(),module)
    except ValueError:layout={'header':0,'mapping':{},'wide':False,'module':None}
    if fonds:layout={'header':0,'mapping':{},'wide':False}
    header=st.number_input('Строка заголовков · '+sheet,min_value=0,max_value=min(31,len(raw)),value=layout['header']+1,key=prefix+'_header',help='Нумерация с 1. Значение 0 — заголовков нет, первая строка содержит данные.')-1
    token=prefix+'_h'+str(header)+'_'+module
    if header!=layout['header']:
        try:
            layout=pressure_layout(raw.iloc[header:].reset_index(drop=True)) if pressure and header>=0 else {'mapping':column_map(list(raw.iloc[header])) if header>=0 else {},'wide':False}
        except ValueError:layout={'mapping':{},'wide':False}
    labels=list(raw.iloc[header]) if header>=0 else ['Колонка '+str(i+1) for i in range(raw.shape[1])]
    labels=['' if pd.isna(v) else str(v).strip() for v in labels]
    edits=st.data_editor(pd.DataFrame({'Колонка':range(1,len(labels)+1),'Исходная шапка':labels,'Используемое имя':labels}),hide_index=True,disabled=['Колонка','Исходная шапка'],key=token+'_names',use_container_width=True)
    names={str(i):str(v).strip() for i,v in enumerate(edits['Используемое имя'])}
    if pressure:
        detected='pressure_match';wide=st.selectbox('Структура · '+sheet,[False,True],index=int(layout.get('wide',False)),key=token+'_wide',format_func=lambda v:'Матрица: даты и колонки скважин' if v else 'Строки: дата, скважина, давление') if not fonds else False
        chosen=['date'] if wide else ['well','fond'] if fonds else ['date','well','value']
    else:
        suggested=module if module!='auto' else layout.get('module') or 'auto'
        detected=st.selectbox('Тип данных · '+sheet,MODULE_CHOICES,index=MODULE_CHOICES.index(suggested),key=token+'_module',format_func=lambda v:'Автоопределение' if v=='auto' else MODULES.get(v,'Подгруппы' if v=='subgroups' else 'Группы'))
        effective=layout.get('module') if detected=='auto' else detected
        wide=st.checkbox('Матрица расходов: скважины по колонкам',value=layout.get('wide',False),disabled=effective not in ('production',None),key=token+'_wide')
        required=REQUIRED.get(effective,{'production':['well','date','q'],'gdi':['well','date','q'],'response':['well','date','horizon'],'object_pressure':['date','pressure'],'groups':['well','group'],'subgroups':['well','subgroup']}.get(effective,[]))
        defaults=list(dict.fromkeys(list(layout.get('mapping',{}))+sorted(required)))
        chosen=['date'] if wide else st.multiselect('Поля для сопоставления · '+sheet,list(ALIASES),default=defaults,key=token+'_fields',format_func=lambda f:FIELDS[f])
        if detected=='auto':detected=effective
    mapping={};columns=list(range(len(labels)));valid=True
    display=lambda i:'— не выбрано —' if i==-1 else str(i+1)+' · '+(names[str(i)] or '(пустая шапка)')
    for field in chosen:
        default=layout.get('mapping',{}).get(field,-1)
        col=st.selectbox(FIELDS[field]+' ← колонка · '+sheet,[-1]+columns,index=default+1 if default in columns else 0,key=token+'_'+field,format_func=display)
        if col>=0:mapping[field]=col
    if len(set(mapping.values()))!=len(mapping):st.error('Одной колонке назначены разные поля. Исправьте сопоставление.');valid=False
    wellcols=[];fond_pairs=[]
    if wide:
        datecol=mapping.get('date',0)
        candidates=[i for i in columns if i!=datecol]
        wellcols=st.multiselect('Колонки скважин · '+sheet,candidates,default=[i for i in candidates if names[str(i)] and not names[str(i)].startswith('Unnamed:')],key=token+'_wellcols',format_func=display)
        if not wellcols:valid=False;st.warning('Выберите хотя бы одну колонку скважины.')
        if pressure:
            from app.modules.pressure_match import well_id
            ids=[well_id(names[str(i)]) for i in wellcols]
            if len(ids)!=len(set(ids)):st.warning('В шапке повторяются номера скважин. Они будут обработаны по выбранному правилу повторных записей; можно отключить лишние колонки.')
    if fonds:
        wells=[j for j,v in enumerate(labels) if re.search(r'скваж|well|^скв',v,re.I)]
        types=[j for j,v in enumerate(labels) if re.search(r'тип|type|фонд|fond',v,re.I)]
        count=st.number_input('Число пар «скважина / фонд» · '+sheet,1,len(columns),max(1,len(wells)),key=token+'_pairs')
        for n in range(count):
            a,b=st.columns(2)
            wc=a.selectbox('Скважина · пара '+str(n+1),columns,index=wells[n] if n<len(wells) else 0,key=token+'_fw'+str(n),format_func=display)
            fc=b.selectbox('Фонд · пара '+str(n+1),columns,index=types[n] if n<len(types) else min(1,len(columns)-1),key=token+'_ff'+str(n),format_func=display)
            if wc==fc:valid=False;st.error('Скважина и фонд должны быть в разных колонках.')
            fond_pairs.append([wc,fc])
    if not pressure and detected is None:
        if wide:detected='production'
        else:
            semantic=[None]*len(columns)
            for f,c in mapping.items():semantic[c]=f
            inferred=detect_layout([semantic]+raw.iloc[max(0,header+1):].values.tolist())
            detected=inferred['module']
    return {'enabled':True,'valid':valid,'module':detected,'header':int(header),'mapping':mapping,'wide':wide,'datecol':mapping.get('date',0),'wellcols':wellcols,'names':names,'fond_pairs':fond_pairs}

def file_editor(content,name,prefix,module='auto'):
    prefix+='_'+hashlib.sha256(content).hexdigest()[:12]
    st.subheader(name)
    encoding,delimiter=text_options(content,name,prefix)
    fmt,tables=samples(content,name,encoding,delimiter)
    st.caption('Формат по содержимому: '+fmt.upper())
    names=list(tables)
    fs=next((n for n in names if any(k in n.lower() for k in ('факт','hist','fact'))),None)
    ms=[n for n in names if any(k in n.lower() for k in ('модел','gdm','model'))]
    if module=='auto' and fs and ms:
        st.info('Распознана книга кроссплота давлений: факт, модель и фонды.')
        fact=st.selectbox('Лист факта · '+name,names,index=names.index(fs),key=prefix+'_fact')
        models=st.multiselect('Листы моделей · '+name,[n for n in names if n!=fact],default=[n for n in ms if n!=fact],key=prefix+'_models')
        fonds=[n for n in names if 'fond' in n.lower() or 'фонд' in n.lower()]
        fonds=st.multiselect('Листы фондов · '+name,[n for n in names if n!=fact and n not in models],default=[n for n in fonds if n!=fact and n not in models],key=prefix+'_fonds')
        obj=st.text_input('Объект · '+name,Path(name).stem,key=prefix+'_object')
        options={}
        for sheet in [fact]+models+fonds:
            with st.container(border=True):options[sheet]=sheet_editor(tables[sheet],sheet,prefix+'_'+sheet,pressure=True,fonds=sheet in fonds)
        return {'sheets':options,'encoding':encoding,'delimiter':delimiter,'pressure_book':True,'fact':fact,'models':models,'fonds':fonds,'object':obj,'duplicate':st.selectbox('Повторы скважина / дата · '+name,['first','last','mean','error'],key=prefix+'_duplicate',format_func=lambda x:{'first':'Первая запись','last':'Последняя запись','mean':'Среднее','error':'Остановить импорт'}[x])}
    options={}
    for sheet,raw in tables.items():
        with st.container(border=True):options[sheet]=sheet_editor(raw,sheet,prefix+'_'+sheet,module)
    return {'sheets':options,'encoding':encoding,'delimiter':delimiter}

def parse_pressure_book(content,name,options):
    return import_rules.parse_pressure_book(content,name,options,full_tables(content,name,options['encoding'],options['delimiter']))


def preview_project(file):
    """Project archives have a fixed schema rather than spreadsheet headings."""
    import io,zipfile
    with st.container(border=True):
        st.markdown('**Предпросмотр проекта · '+file.name+'**')
        try:
            if file.name.lower().endswith('.json'):
                obj=json.loads(file.getvalue());st.json({k:obj.get(k) for k in ('name','version','settings')})
                records=obj.get('records',[]);st.caption('Записей: '+str(len(records)))
                if records:st.dataframe(pd.DataFrame(records[:30]),use_container_width=True)
            else:
                with zipfile.ZipFile(io.BytesIO(file.getvalue())) as z:
                    info=z.getinfo('manifest.json')
                    if info.file_size>10*1024**2:raise ValueError('Слишком большой manifest.json.')
                    obj=json.loads(z.read(info));st.json({k:obj.get(k) for k in ('name','version','tables')})
                    st.dataframe(pd.DataFrame([{'Файл':i.filename,'Размер, байт':i.file_size} for i in z.infolist() if not i.is_dir()]).head(100),hide_index=True,use_container_width=True)
            st.caption('Резервная копия имеет фиксированную структуру проекта. Настройка шапки применяется к импорту таблиц Excel / ODS / TXT / CSV.')
        except Exception as error:st.error('Предпросмотр проекта: '+str(error))
