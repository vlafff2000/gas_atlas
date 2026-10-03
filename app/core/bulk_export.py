"""One disk-backed artifact per module. Figures are rendered sequentially."""
from dataclasses import dataclass
from pathlib import Path
import gc
import json
import tempfile
import zipfile
import pandas as pd
from .export import figure_bytes,safe_name,safe_table,xlsx_bytes,csv_bytes
from .config import MODULES

@dataclass
class ExportResult:
    paths: list
    planned: int
    completed: int
    files: int
    errors: list

def _json(value):return json.dumps(value,ensure_ascii=False,indent=2,default=str)

def _modules(plan):
    groups={}
    for i,job in enumerate(plan.jobs,1):groups.setdefault(getattr(job,'module','') or 'results',[]).append((i,job))
    module_tables=getattr(plan,'module_tables',{})
    for module in module_tables:groups.setdefault(module,[])
    if not groups:groups={'results':[]}
    for module,jobs in groups.items():
        yield module,jobs,module_tables.get(module,plan.tables if len(groups)==1 else {})

def export_plan(plan,store,pid,formats=('svg','pdf'),dpi=300,width_mm=220,metadata=None,progress=None,chunk_size=40,max_part_bytes=70*1024**2):
    # Legacy keyword arguments remain accepted; they no longer split the output.
    if chunk_size<1:raise ValueError('Размер части должен быть положительным')
    if any(fmt not in ('svg','pdf','png') for fmt in formats):raise ValueError('Неизвестный формат графика')
    paths=[];errors=[];completed=0;files=0;metadata=metadata or {};processed=0
    directory=store.path(pid)/'exports';directory.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='pending_export_',dir=str(directory)) as tmp:
        for module,jobs,tables in _modules(plan):
            label=MODULES.get(module,'Результаты');current=Path(tmp)/'module.zip';local_errors=[];records=[];good_count=0
            with zipfile.ZipFile(current,'w',zipfile.ZIP_DEFLATED,allowZip64=True) as z:
                for i,job in jobs:
                    good=False;fig=None
                    if formats:
                        try:fig=job.render()
                        except Exception as error:local_errors.append({'График':job.name,'Формат':'Все','Ошибка':str(error)})
                        if fig is not None:
                            for fmt in formats:
                                try:
                                    content=figure_bytes(fig,fmt,dpi,width_mm);member='charts/{:05}_{}.{}'.format(i,safe_name(job.name),fmt)
                                    z.writestr(member,content);files+=1;good=True;records.append({'chart':job.name,'format':fmt,'file':member,'status':'ok'})
                                    del content
                                except Exception as error:local_errors.append({'График':job.name,'Формат':fmt,'Ошибка':str(error)})
                    completed+=int(good);good_count+=int(good);processed+=1;del fig
                    if progress:progress(processed/max(1,len(plan.jobs)+1),'График {} из {}: {}'.format(processed,len(plan.jobs),job.name))
                    if processed%10==0:gc.collect()
                for i,(name,df) in enumerate(tables.items(),1):
                    try:
                        staged=Path(tmp)/'table.csv';safe_table(df).to_csv(staged,index=False,sep=';',decimal=',',encoding='utf-8-sig',chunksize=10000)
                        z.write(staged,'tables/{:03}_{}.csv'.format(i,safe_name(name)))
                    except Exception as error:local_errors.append({'График':'Таблица '+name,'Формат':'csv','Ошибка':str(error)})
                if tables:
                    if any(len(d)>1_048_575 for d in tables.values()):z.writestr('XLSX_LIMIT.txt','Полные таблицы сохранены в CSV. Превышен лимит строк Excel.')
                    else:
                        try:
                            if module=='pressure_match':
                                from app.modules.pressure_workbook import workbook_bytes
                                z.writestr('results.xlsx',workbook_bytes(tables,metadata.get('options',{}).get(module,{})))
                            else:z.writestr('results.xlsx',xlsx_bytes(tables))
                        except Exception as error:local_errors.append({'График':'Общая книга','Формат':'xlsx','Ошибка':str(error)})
                z.writestr('parameters.json',_json({**metadata,'module':module}))
                z.writestr('export_manifest.json',_json({'module':module,'planned_charts':len(jobs),'completed_charts':good_count,'chart_files':len(records),'formats':list(formats),'table_count':len(tables),'parts':1,'files':records,'errors':local_errors,'status':'partial' if local_errors else 'complete'}))
                if local_errors:z.writestr('export_errors.csv',csv_bytes(pd.DataFrame(local_errors)))
            errors.extend(local_errors);paths.append(store.save_export_file(pid,safe_name(label)+'.zip',current,{**metadata,'module':module}))
    if progress:progress(1.,'Экспорт завершен. Сохранено графиков: '+str(completed))
    return ExportResult(paths,len(plan.jobs),completed,files,errors)

def export_word(plan,store,pid,project,captions=None,metadata=None,progress=None,chunk_size=40):
    from .documents import report_docx
    from .reporting import FigureMap
    if not plan.jobs:raise ValueError('Нет графиков для Word-отчета')
    paths=[];errors=[];count=0;processed=0;directory=store.path(pid)/'exports';directory.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='pending_word_',dir=str(directory)) as tmp:
        for module,jobs,_ in _modules(plan):
            if not jobs:continue
            local_errors=[];label=MODULES.get(module,'Результаты');current=Path(tmp)/'module.docx'
            def update(value):
                if progress:progress((processed+value*len(jobs))/len(plan.jobs),'Word · '+label)
            # Failed factories are isolated; successful figures are yielded one at a time.
            class Figures:
                def __len__(self):return len(jobs)
                def items(self):
                    for _,job in jobs:
                        try:yield job.name,job.render()
                        except Exception as error:local_errors.append({'График':job.name,'Формат':'docx','Ошибка':str(error)})
            report_docx(Figures(),project+' · '+label,captions,progress=update,errors=local_errors,target=current)
            successful=len(jobs)-len(local_errors);count+=successful;processed+=len(jobs);errors.extend(local_errors)
            paths.append(store.save_export_file(pid,safe_name(label)+'.docx',current,{**(metadata or {}),'module':module,'errors':local_errors}))
            gc.collect()
    if progress:progress(1.,'Word: готов единый документ каждого модуля')
    return ExportResult(paths,len(plan.jobs),count,count,errors)

def bundle_exports(store,pid,paths,metadata=None):
    unique=list(dict.fromkeys(str(p) for p in paths));directory=store.path(pid)/'exports'
    if not unique:raise ValueError('Нет созданных файлов для общего скачивания.')
    with tempfile.TemporaryDirectory(prefix='pending_bundle_',dir=str(directory)) as tmp:
        target=Path(tmp)/'all.zip'
        with zipfile.ZipFile(target,'w',zipfile.ZIP_STORED,allowZip64=True) as z:
            for i,name in enumerate(unique,1):
                p=Path(name)
                if not p.exists():raise ValueError('Файл не найден: '+p.name)
                z.write(p,p.name)
            z.writestr('files.json',_json([Path(p).name for p in unique]))
        return store.save_export_file(pid,'Все_созданные_файлы.zip',target,metadata or {})


# Presets saved by older versions (shared by 5.8 export panel and Atlas 6).
def migrate_preset(values):
    values=dict(values);modules=list(values.get('modules',[]))
    view=values.get('production_view')
    if view in ('hist','mixed'):
        if 'histograms' not in modules:modules.append('histograms')
        if view=='hist':modules=[m for m in modules if m!='production']
        for field in ('wells','groups','split','direction','histaxis','hist_size','groupmode','size','panels'):
            if 'production_'+field in values:values.setdefault('histograms_'+field,values['production_'+field])
        values['production_view']='curve'
    for kind in ('withdrawal','injection'):
        if 'periods_'+kind in values:
            values.setdefault('production_periods_'+kind,values['periods_'+kind]);values.setdefault('histograms_periods_'+kind,values['periods_'+kind])
    values['modules']=modules;return values
