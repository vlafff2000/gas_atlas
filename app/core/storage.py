"""Atomic snapshot projects (Parquet), SQLite audit log, guarded backup import."""
from __future__ import annotations
import contextlib
import datetime as dt
import hashlib
import io
import json
import os
import re
from pathlib import Path
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
import pandas as pd
import portalocker
from .config import DEFAULT_SETTINGS, STORAGE, VERSION

def _keep_snapshots():
    try: return max(2,int(os.environ.get('GAS_ATLAS_SNAPSHOTS','10')))
    except ValueError: return 10
NO_DATA='none'   # «копия» до первого импорта: проект без данных
KEEP_SNAPSHOTS=_keep_snapshots()   # копий данных на проект: для отката импорта (было 2)

def atomic_json(path, value):
    path=Path(path); tmp=path.with_suffix('.tmp-'+uuid.uuid4().hex)
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str),encoding='utf8')
    os.replace(tmp,path)

class Store:
    def __init__(self, root=STORAGE):
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True)
        self.projects=self.root/'projects'; self.projects.mkdir(exist_ok=True)
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, project TEXT, timestamp TEXT, action TEXT, details TEXT)')

    @contextlib.contextmanager
    def db(self):
        connection=sqlite3.connect(str(self.root/'history.sqlite'),timeout=30)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def path(self,pid):
        if not isinstance(pid,str) or len(pid)!=32 or any(c not in '0123456789abcdef' for c in pid):
            raise ValueError('Некорректный идентификатор проекта')
        return self.projects/pid

    def event(self,pid,action,details):
        with self.db() as db:
            db.execute('INSERT INTO events(project,timestamp,action,details) VALUES (?,?,?,?)',
                (pid,dt.datetime.now(dt.timezone.utc).isoformat(),action,json.dumps(details,ensure_ascii=False,default=str)))

    def history(self,pid):
        with self.db() as db:
            return pd.read_sql_query('SELECT timestamp AS Дата, action AS Действие, details AS Подробности FROM events WHERE project=? ORDER BY id DESC LIMIT 500',db,params=(pid,))

    def list(self):
        out=[]
        for path in self.projects.glob('*/manifest.json'):
            try: out.append(json.loads(path.read_text('utf8')))
            except (ValueError,OSError): continue
        return sorted(out,key=lambda x:x['updated'],reverse=True)

    def create(self,name,demo=False):
        name=name.strip()
        if not name: raise ValueError('Введите название проекта')
        pid=uuid.uuid4().hex; path=self.path(pid); path.mkdir()
        (path/'snapshots').mkdir(); (path/'originals').mkdir()
        manifest={'id':pid,'name':name[:120],'demo':demo,'version':VERSION,'revision':0,
                  'updated':dt.datetime.now(dt.timezone.utc).isoformat(),'tables':{},'snapshot':None,
                  'settings':dict(DEFAULT_SETTINGS),'groups':{},'imports':[]}
        atomic_json(path/'manifest.json',manifest); self.event(pid,'Создание',{'name':name})
        return pid

    def manifest(self,pid):
        return json.loads((self.path(pid)/'manifest.json').read_text('utf8'))

    def load(self,pid):
        m=self.manifest(pid); data={}
        if m['snapshot']:
            for name in m['tables']:
                data[name]=pd.read_parquet(self.path(pid)/'snapshots'/m['snapshot']/(name+'.parquet'))
        return m,data

    @contextlib.contextmanager
    def lock(self,pid):
        # Native file locks on Windows and POSIX; released on process exit.
        with portalocker.Lock(str(self.path(pid)/'.lock'),mode='a',timeout=30):
            yield

    def commit(self,pid,frames=None,settings=None,groups=None,imports=None,expected=None,action='Сохранение',details=None):
        with self.lock(pid):
            m=self.manifest(pid)
            if expected is not None and m['revision']!=expected:
                raise ValueError('Проект изменен в другой вкладке. Обновите страницу и повторите действие.')
            before=m['snapshot']
            if frames is not None:
                snap=uuid.uuid4().hex; dest=self.path(pid)/'snapshots'/snap; dest.mkdir()
                try:
                    for name,frame in frames.items():
                        if name not in ('production','gdi','response','object_pressure','operations','water','bottom','construction','pressure_match','plan'): raise ValueError('Неизвестный модуль')
                        clean=frame.copy(deep=False);clean.attrs={}
                        clean.to_parquet(dest/(name+'.parquet'),index=False,compression='zstd')
                except Exception:
                    shutil.rmtree(dest); raise
                m['snapshot']=snap; m['tables']={k:len(v) for k,v in frames.items()}
            if settings is not None: m['settings']=settings
            if groups is not None: m['groups']=groups
            if imports is not None: m['imports']=imports
            m['version']=VERSION
            m['revision']+=1; m['updated']=dt.datetime.now(dt.timezone.utc).isoformat()
            atomic_json(self.path(pid)/'manifest.json',m)
            # Новая копия данных — запись о том, какая была до неё: по ней откатывают импорт (``rollback``).
            kept={'snapshot':m['snapshot'],'previous_snapshot':before} if frames is not None else {}
            self.event(pid,action,{**(details or {}),**kept,'revision':m['revision'],'rows':m['tables']})
            # Keep the last KEEP_SNAPSHOTS data snapshots for recovery; never touch originals or the current one.
            snapshots=sorted((self.path(pid)/'snapshots').iterdir(),key=lambda p:p.stat().st_mtime,reverse=True)
            for stale in snapshots[KEEP_SNAPSHOTS:]:
                if stale.name==m['snapshot']: continue
                try: shutil.rmtree(stale)
                except PermissionError:
                    # Windows can keep a reader's file open briefly. Retry next commit.
                    continue
            return m

    def versions(self,pid):
        """Копии данных, которые ещё можно вернуть: снимок, когда создан, действие, строк; новые сверху."""
        m=self.manifest(pid); root=self.path(pid)/'snapshots'; out=[]
        for _,row in self.history(pid).iterrows():
            try: d=json.loads(row['Подробности'])
            except ValueError: continue
            snap=d.get('snapshot') if isinstance(d,dict) else None
            if snap and (root/snap).is_dir():
                out.append({'snapshot':snap,'date':row['Дата'],'action':row['Действие'],'revision':d.get('revision'),
                            'rows':d.get('rows') or {},'current':snap==m['snapshot'],
                            'before':(d['previous_snapshot'] if (root/d['previous_snapshot']).is_dir() else None) if d.get('previous_snapshot') else NO_DATA})
        return out

    def rollback(self,pid,snapshot,expected=None):
        """Вернуть данные копии ``snapshot``: новой ревизией (история не стирается), настройки и группы не трогаются."""
        if snapshot==NO_DATA: return self.commit(pid,{},expected=expected,action='Откат данных',details={'restored_snapshot':NO_DATA})
        if not re.fullmatch(r'[0-9a-f]{32}',str(snapshot)): raise ValueError('Неверная копия данных')
        src=self.path(pid)/'snapshots'/snapshot
        if not src.is_dir(): raise ValueError('Эта копия данных уже удалена: хранятся последние %d.'%KEEP_SNAPSHOTS)
        frames={f.stem:pd.read_parquet(f) for f in sorted(src.glob('*.parquet'))}
        return self.commit(pid,frames,expected=expected,action='Откат данных',details={'restored_snapshot':snapshot})

    def keep_original(self,pid,path):
        path=Path(path); sha=hashlib.sha256()
        with path.open('rb') as f:
            for chunk in iter(lambda:f.read(1024**2),b''): sha.update(chunk)
        checksum=sha.hexdigest(); dest=self.path(pid)/'originals'/(checksum[:16]+'_'+path.name)
        if not dest.exists(): shutil.copy2(path,dest)
        return {'name':path.name,'sha256':checksum,'file':dest.name,'bytes':path.stat().st_size}

    def backup(self,pid,originals=True):
        with self.lock(pid):
            m=self.manifest(pid); buf=io.BytesIO()
            with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
                z.writestr('manifest.json',json.dumps(m,ensure_ascii=False))
                if m['snapshot']:
                    for name in m['tables']: z.write(self.path(pid)/'snapshots'/m['snapshot']/(name+'.parquet'),'data/'+name+'.parquet')
                if originals:
                    for p in (self.path(pid)/'originals').iterdir(): z.write(p,'originals/'+p.name)
                for p in (self.path(pid)/'exports').glob('*'):
                    if p.is_file():z.write(p,'exports/'+p.name)
                z.writestr('history.csv',self.history(pid).to_csv(index=False))
            return buf.getvalue()

    def restore(self,content):
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            if sum(i.file_size for i in z.infolist())>3*1024**3: raise ValueError('Архив больше 3 ГБ после распаковки')
            names=z.namelist()
            if len(names)!=len(set(names)): raise ValueError('Архив содержит повторяющиеся имена')
            for n in names:
                if n.startswith('/') or '..' in Path(n).parts or '\\' in n or ':' in n: raise ValueError('Некорректные пути в архиве')
            m=json.loads(z.read('manifest.json'))
            if not isinstance(m.get('settings'),dict) or not isinstance(m.get('groups'),dict): raise ValueError('Некорректный манифест')
            data={}
            for name in m.get('tables',{}):
                if name not in ('production','gdi','response','object_pressure','operations','water','bottom','construction','pressure_match','plan'): raise ValueError('Неизвестный модуль в архиве')
                df=pd.read_parquet(io.BytesIO(z.read('data/'+name+'.parquet')))
                req={'production':{'well','date','q','kind'},'gdi':{'well','date','q','dp2'},'response':{'well','date','horizon','level'},'object_pressure':{'date','pressure'},'operations':{'well','date','kind','work_hours'},'water':{'well','date','water_flag','water_rate'},'bottom':{'well','date','bottom_m'},'construction':{'well','date','element','top_m','bottom_m'},'pressure_match':{'well','date','fact','model','object','scenario','fond'},'plan':{'group','date','plan_volume','kind'}}[name]
                if not req<=set(df): raise ValueError('Неполные данные в архиве')
                data[name]=df
            pid=self.create(m.get('name','Восстановленный проект')+' (копия)',m.get('demo',False))
            for n in names:
                if n.startswith('originals/') and len(Path(n).parts)==2:
                    (self.path(pid)/n).write_bytes(z.read(n))
            self.commit(pid,data,settings={**DEFAULT_SETTINGS,**m['settings']},groups=m['groups'],imports=m.get('imports',[]),action='Восстановление из архива')
            for n in names:
                if n.startswith('exports/') and len(Path(n).parts)==2:
                    (self.path(pid)/'exports').mkdir(exist_ok=True);(self.path(pid)/n).write_bytes(z.read(n))
            if 'history.csv' in names:
                history=pd.read_csv(io.BytesIO(z.read('history.csv'))).fillna('')
                if {'Дата','Действие','Подробности'}<=set(history):
                    with self.db() as db:
                        for row in history.iloc[::-1].itertuples(index=False,name=None):
                            stamp,action,details=row[:3]
                            json.loads(details)
                            db.execute('INSERT INTO events(project,timestamp,action,details) VALUES (?,?,?,?)',(pid,stamp,action,details))
            return pid

    def import_legacy(self,content):
        """Migrate v1 .gas.json into a new project; never overwrite an existing one."""
        from .loader import dates,numeric,well_ids,merge_frames
        obj=json.loads(content)
        if obj.get('version')!=1 or not isinstance(obj.get('records'),list) or len(obj['records'])>1_000_000:
            raise ValueError('Ожидается проект версии 1 в формате .gas.json (до 1 млн строк).')
        d=pd.DataFrame(obj['records'])
        if d.empty or not {'well','date','flow','kind'}<=set(d):
            raise ValueError('Нет корректной таблицы records.')
        d['well']=well_ids(d.well); d['date']=dates(d.date); d['q']=numeric(d.flow)
        if d.date.isna().any() or d.well.eq('').any() or d.q.isna().any() or d.q.lt(0).any() or not d.kind.isin(['withdrawal','injection']).all():
            raise ValueError('В старом проекте есть некорректные даты, расходы или типы данных. Перенос отменен.')
        for c in ('season','year'): d[c]=d[c].fillna('').astype(str) if c in d else ''
        d['group']=d.get('source',pd.Series('Без группы',index=d.index)).fillna('Без группы')
        d['subgroup']='';d['file']='Проект версии 1';d['sheet']='records';d['_row']=range(1,len(d)+1)
        d=d.drop(columns=[c for c in ('flow','meta','source') if c in d])
        d,_=merge_frames(None,d,'production')
        previous=obj.get('settings',{}); settings={**DEFAULT_SETTINGS}
        for old,new in [('start','season_start'),('end','season_end')]:
            value=previous.get(old,settings[new])
            if not isinstance(value,int) or not 1<=value<=12: raise ValueError('Некорректные месяцы сезона в старом проекте')
            settings[new]=value
        pid=self.create(str(obj.get('name') or 'Проект версии 1'),obj.get('demo',False))
        groups=obj.get('mapping',{})
        if not isinstance(groups,dict): groups={}
        groups={str(w):{k:str(v) for k,v in entry.items() if k in ('group','subgroup')} for w,entry in groups.items() if isinstance(entry,dict)}
        self.commit(pid,{'production':d},settings=settings,groups=groups,action='Перенос проекта версии 1')
        return pid

    def rename(self,pid,name,expected=None):
        name=name.strip()
        if not name:raise ValueError('Введите название проекта')
        with self.lock(pid):
            m=self.manifest(pid)
            if expected is not None and m['revision']!=expected:raise ValueError('Проект изменен. Обновите страницу.')
            old=m['name'];m['name']=name[:120];m['revision']+=1;m['updated']=dt.datetime.now(dt.timezone.utc).isoformat()
            atomic_json(self.path(pid)/'manifest.json',m)
            self.event(pid,'Переименование',{'before':old,'after':m['name']})

    def save_export(self,pid,filename,content,metadata=None):
        from .export import safe_name
        directory=self.path(pid)/'exports';directory.mkdir(exist_ok=True)
        filename=dt.datetime.now().strftime('%Y%m%d_%H%M%S_')+uuid.uuid4().hex[:6]+'_'+safe_name(filename)
        path=directory/filename
        path.write_bytes(content)
        atomic_json(path.with_name(path.name+'.json'),metadata or {})
        self.event(pid,'Сохранение экспорта',{'file':filename,'bytes':len(content)})
        return path

    def exports(self,pid):
        directory=self.path(pid)/'exports'
        return sorted([p for p in directory.glob('*') if p.is_file() and p.suffix!='.json'],key=lambda p:p.stat().st_mtime,reverse=True)

    def save_export_file(self,pid,filename,source,metadata=None):
        """Commit an already closed report without duplicating its bytes in RAM."""
        from .export import safe_name
        directory=self.path(pid)/'exports';directory.mkdir(exist_ok=True)
        filename=dt.datetime.now().strftime('%Y%m%d_%H%M%S_')+uuid.uuid4().hex[:6]+'_'+safe_name(filename)
        path=directory/filename;temporary=path.with_name(path.name+'.pending')
        try:
            with Path(source).open('rb') as src,temporary.open('wb') as dst:
                shutil.copyfileobj(src,dst,1024**2);dst.flush();os.fsync(dst.fileno())
            os.replace(temporary,path)
        finally:
            if temporary.exists():temporary.unlink()
        atomic_json(path.with_name(path.name+'.json'),metadata or {})
        self.event(pid,'Сохранение экспорта',{'file':filename,'bytes':path.stat().st_size})
        return path
