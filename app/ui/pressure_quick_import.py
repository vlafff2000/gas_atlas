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
from app.core import tabular,profiles
from app.modules import pressure_match as pm
from app.ui.import_editor import pressure_layout,pressure_table,fonds_table,sheet_editor,text_options

from app.core.pressure_import import (FACT,MODEL,FOND,SKIP,ROLES,FACT_RE,MODEL_RE,FOND_RE,SKIP_RE,ROLE_WORDS,DUPLICATES,TEXT_TYPES,MAX_PARALLEL_NOTE,is_binary_book,_labels,auto_spec,guess_role,guess_object,guess_scenario,parse_file,_normalize,refresh,describe,build_rows,assemble)

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
                kind='pressure_fond' if role==FOND else 'pressure'
                if st.checkbox('Запомнить для файлов с такой же шапкой',value=profiles.find(record['raw'].head(31),kind) is not None,key=key('pmq_remember_'+sha[:10]+sheet),help='В следующий раз такая разметка применится автоматически.'):profiles.save(record['raw'].head(31),spec,kind)
                else:profiles.forget(record['raw'].head(31),spec,kind)
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
            st.session_state[key('pm_import_open')]=False
        except Exception as error:st.session_state[key('pmq_done')]=('error',str(error))
    st.button('Сохранить в проект',type='primary',key=key('pmq_commit'),on_click=commit,disabled=bool(held['errors']))
