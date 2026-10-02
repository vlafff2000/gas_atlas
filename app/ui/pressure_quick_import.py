"""Quick bulk import for the pressure crossplot.

Many workbooks / text files are dropped at once. Every sheet is classified (fact / model / fond / skip),
its layout is detected automatically and the whole batch is reviewed in ONE table instead of one long
form per file. A single sheet can still be opened in the detailed editor when detection is wrong.
Each file is read exactly once per session (not on every Streamlit rerun).
"""
import hashlib
import json
import re
import tempfile
from pathlib import Path
import pandas as pd
import streamlit as st
from app.core import tabular
from app.core.logging_utils import show_error
from app.modules import pressure_match as pm
from app.ui.import_editor import pressure_layout,pressure_table,fonds_table,sheet_editor,text_options

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
            rows.append({'Исп.':use,'Файл':name,'Лист':s,'Роль':role,'Объект':obj,'Сценарий':scenario if role==MODEL else '','Значений':valid,'Скважин':wells,'Период':period,'Структура':layout,'Статус':status,'_sha':sha})
    return rows

def assemble(rows,cache,duplicate):
    """Pair fact and model rows per object. Returns (data,notes,errors,warnings,summary)."""
    notes=[];errors=[];warnings=[];parts=[];groups={}
    for r in rows:
        if r['Исп.'] and r['Роль']!=SKIP:groups.setdefault(r['Объект'].strip() or 'Объект',[]).append(r)
    if not groups:raise ValueError('Не выбран ни один лист.')
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
        if not facts:errors.append('Объект «'+obj+'»: не выбран лист или файл с фактом.');continue
        if not models:warnings.append('Объект «'+obj+'»: нет моделей, объект пропущен.');continue
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

def render(store,pid,manifest,raw_frames,key):
    state=st.session_state.setdefault(key('pmq_state'),{'cache':{},'choices':{},'overrides':{}})
    cache,choices,overrides=state['cache'],state['choices'],state['overrides']
    top=st.columns([3,1.4])
    with top[0]:
        uploaded=st.file_uploader('Перетащите сразу все файлы: книги Excel / ODS, CSV, TXT',type=TEXT_TYPES,accept_multiple_files=True,key=key('pmq_upload_'+str(state.get('generation',0))),
            help='Книга с листами «Факт», «Модель…», «Фонд» распознается автоматически. Отдельные файлы: «…факт…» и «…модель…» в названии. Все листы всех файлов проверяются в одной таблице.')
    duplicate=top[1].selectbox('Повторные скважина / дата',list(DUPLICATES),format_func=DUPLICATES.get,key=key('pmq_duplicates'))
    if not uploaded:
        st.info('Выберите файлы. Программа сама определит факт, модели, фонды, шапку и структуру. Если данные уже есть в проекте, новые объекты добавятся к ним.')
        return
    files={}
    for f in uploaded:
        content=f.getvalue();files[hashlib.sha256(content+f.name.encode()).hexdigest()]=(f.name,content)
    for sha in [s for s in cache if s not in files]:cache.pop(sha,None)
    missing=[sha for sha in files if sha not in cache]
    if missing:
        bar=st.progress(0.,text='Чтение файлов…')
        for i,sha in enumerate(missing):
            name,content=files[sha];bar.progress(i/len(missing),text='Чтение: '+name+' ('+str(i+1)+' из '+str(len(missing))+')')
            try:cache[sha]=parse_file(name,content,*overrides.get(('opts',sha),('auto','auto')))
            except Exception as error:cache[sha]={'format':'?','sheets':{},'error':str(error)}
        bar.empty()
    bad=[files[sha][0]+': '+cache[sha]['error'] for sha in files if cache[sha].get('error')]
    for message in bad:st.error('Файл не прочитан — '+message)
    files_ok={sha:v for sha,v in files.items() if not cache[sha].get('error')}
    if not files_ok:return
    # apply per-sheet detailed overrides
    for (sha,sheet),spec in [(k,v) for k,v in overrides.items() if k[0]!='opts']:
        if sha in cache and sheet in cache[sha]['sheets'] and cache[sha]['sheets'][sheet].get('spec_applied')!=json.dumps(spec,sort_keys=True,default=str):
            record=cache[sha]['sheets'][sheet]
            if spec.get('fonds'):record['fond_spec']={k:v for k,v in spec.items() if k!='fonds'}
            else:refresh(record,spec)
            record['spec_applied']=json.dumps(spec,sort_keys=True,default=str)
    rows=build_rows(files_ok,cache,choices,manifest['name'])
    sheets_count=len(rows);counts={'Файлов':len(files_ok),'Листов':sheets_count,'Используется':sum(r['Исп.'] for r in rows)}
    cols=st.columns(4)
    for col,(label,value) in zip(cols,list(counts.items())+[('Объектов',len({r['Объект'] for r in rows if r['Исп.'] and r['Роль']!=SKIP}))]):col.metric(label,value)
    if len(files_ok)>MAX_PARALLEL_NOTE:st.caption('Загружено много файлов: листы отображаются в одной таблице. Фильтр по статусу — ниже.')
    table=pd.DataFrame(rows)
    only_issues=st.checkbox('Показать только листы с замечаниями',False,key=key('pmq_issues')) if len(rows)>12 else False
    view=table[table['Статус'].ne('OK')|table['Исп.'].eq(False)&table['Роль'].ne(SKIP)] if only_issues else table
    signature=hashlib.sha256(json.dumps([r['_sha']+r['Лист'] for r in rows]).encode()).hexdigest()[:10]
    edited=st.data_editor(view.drop(columns='_sha'),hide_index=True,use_container_width=True,height=min(560,45+35*len(view)),key=key('pmq_table_'+signature+('i' if only_issues else '')),
        disabled=['Файл','Лист','Значений','Скважин','Период','Структура','Статус'],
        column_order=['Исп.','Файл','Лист','Роль','Объект','Сценарий','Статус','Значений','Скважин','Период','Структура'],
        column_config={'Исп.':st.column_config.CheckboxColumn('Исп.',width='small',help='Использовать лист'),
            'Роль':st.column_config.SelectboxColumn('Роль',options=ROLES,required=True,width='medium',help='Факт — X, Модель — Y, Фонд — справочник «скважина → тип»'),
            'Объект':st.column_config.TextColumn('Объект',help='Факт и модели с одинаковым названием объекта сопоставляются между собой'),
            'Сценарий':st.column_config.TextColumn('Сценарий',help='Название модели на графиках'),
            'Значений':st.column_config.NumberColumn(format='%d'),'Скважин':st.column_config.NumberColumn(format='%d'),'Статус':st.column_config.TextColumn('Статус',width='medium')})
    shas=view['_sha'].tolist();shown=view.reset_index(drop=True)
    for i,row in edited.reset_index(drop=True).iterrows():
        # Only values the user actually changed are remembered; everything else stays automatic.
        entry=choices.setdefault((shas[i],row['Лист']),{})
        for column,field in (('Исп.','use'),('Роль','role'),('Объект','object'),('Сценарий','scenario')):
            value=row[column];before=shown.at[i,column]
            if column=='Исп.':value,before=bool(value),bool(before)
            else:value,before=str(value or '').strip(),str(before or '').strip()
            if value!=before and (value or column=='Сценарий'):entry[field]=value
    rows=build_rows(files_ok,cache,choices,manifest['name'])
    st.caption('Роль, объект и сценарий можно править прямо в таблице. Фактические данные — по оси X, модельные — по оси Y.')
    fine=st.selectbox('Нестандартный лист? Тонкая настройка шапки и колонок',[None]+[(r['_sha'],r['Лист']) for r in rows],format_func=lambda v:'— не нужна —' if v is None else files_ok[v[0]][0]+' · '+v[1],key=key('pmq_fine'))
    if fine:
        sha,sheet=fine;name,content=files_ok[sha];record=cache[sha]['sheets'][sheet]
        with st.container(border=True):
            if not is_binary_book(content):
                enc,delim=text_options(content,name,key('pmq_text_'+sha[:10]))
                if (enc,delim)!=(cache[sha]['encoding'],cache[sha]['delimiter']):
                    overrides[('opts',sha)]=(enc,delim);cache[sha]=parse_file(name,content,enc,delim);st.rerun()
            role=choices.get(fine,{}).get('role',next(r['Роль'] for r in rows if (r['_sha'],r['Лист'])==fine))
            spec=sheet_editor(record['raw'].head(31),sheet,key('pmq_fine_')+sha[:10]+sheet,pressure=True,fonds=role==FOND)
            if spec.get('enabled') and spec.get('valid',True):
                overrides[(sha,sheet)]={**spec,'fonds':True} if role==FOND else spec
            else:overrides.pop(fine,None)
            if st.button('Вернуть автоматические настройки листа',key=key('pmq_reset')):
                overrides.pop(fine,None);record.pop('spec_applied',None);cache[sha]=parse_file(name,content,cache[sha]['encoding'],cache[sha]['delimiter']);st.rerun()
    fingerprint=json.dumps([duplicate,[[r['_sha'],r['Лист'],r['Исп.'],r['Роль'],r['Объект'],r['Сценарий']] for r in rows],[[k[0],k[1],v] for k,v in overrides.items() if k[0]!='opts']],ensure_ascii=False,sort_keys=True,default=str)
    held=st.session_state.get(key('pmq_result'))
    if not held or held['fingerprint']!=fingerprint:
        try:
            with st.spinner('Сопоставление факта и моделей…'):
                data,notes,errors,warnings,summary=assemble(rows,cache,duplicate)
            held={'fingerprint':fingerprint,'data':data,'notes':notes,'errors':errors,'warnings':warnings,'summary':summary}
        except Exception as error:held={'fingerprint':fingerprint,'data':None,'notes':[],'errors':[str(error)],'warnings':[],'summary':None}
        st.session_state[key('pmq_result')]=held
    for message in held['errors']:st.error(message)
    for message in held['warnings']:st.warning(message)
    if held['data'] is None:return
    data=held['data'];st.success('Готово к сохранению: '+str(len(data))+' пар / неполных пар · объектов '+str(data.object.nunique())+' · сценариев '+str(data.scenario.nunique()))
    st.dataframe(held['summary'],hide_index=True,use_container_width=True)
    if held['notes']:
        with st.expander('Замечания сопоставления: '+str(len(held['notes']))):st.dataframe(pd.DataFrame(held['notes']),hide_index=True,use_container_width=True)
    existing='pressure_match' in raw_frames
    mode='Добавить / обновить объекты'
    if existing:
        old=raw_frames['pressure_match'];names=sorted(set(old.object)&set(data.object))
        mode=st.radio('Что делать с уже загруженными данными давлений',['Добавить / обновить объекты','Заменить все данные давлений'],horizontal=True,key=key('pmq_mode'),
            help='«Добавить»: объекты с теми же названиями заменяются, остальные сохраняются.')
        if mode.startswith('Добавить'):st.caption('В проекте объектов: '+str(old.object.nunique())+'. Будут заменены: '+(', '.join(names) if names else 'нет совпадений')+'.')
    def commit():
        try:
            final=data
            if existing and mode.startswith('Добавить'):
                old=raw_frames['pressure_match'].drop(columns=['_point_id'],errors='ignore');final=pd.concat([old[~old.object.isin(data.object.unique())],data],ignore_index=True)
            frames=dict(raw_frames);frames['pressure_match']=final
            store.commit(pid,frames,expected=manifest['revision'],action='Импорт кроссплота давлений',details={'rows':len(data),'files':len(files_ok),'mode':mode,'diagnostics':held['notes']})
            with tempfile.TemporaryDirectory() as tmp:
                for name,content in files_ok.values():
                    path=Path(tmp)/Path(name).name;path.write_bytes(content);store.keep_original(pid,path)
            generation=state.get('generation',0)+1;st.session_state.pop(key('pmq_result'),None)
            st.session_state[key('pmq_state')]={'cache':{},'choices':{},'overrides':{},'generation':generation}
            st.session_state[key('pmq_done')]=('success','Сохранено: '+str(len(data))+' строк, объектов '+str(data.object.nunique()))
            st.session_state[key('pm_show_import')]=False
        except Exception as error:st.session_state[key('pmq_done')]=('error',str(error))
    st.button('Сохранить в проект',type='primary',key=key('pmq_commit'),on_click=commit,disabled=bool(held['errors']))
