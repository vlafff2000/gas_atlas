"""Snapshot-scoped lazy data, immutable prepared views and bounded chart caches."""
from collections import OrderedDict
from collections.abc import Mapping
from functools import wraps
from pathlib import Path
import hashlib
import json
import threading
import copy
import numpy as np
import pandas as pd
from .memo import cache_resource
from . import exclusions


def signature(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str).encode('utf8')).hexdigest()


class FrameIndex:
    def __init__(self,df,module):
        self.owner=id(df);self.rows=len(df)
        self.wells=df.groupby('well',sort=False).indices if 'well' in df else {}
        self.horizons=df.groupby('horizon',sort=False).indices if 'horizon' in df else {}
        self.seasons=df.groupby('season',sort=False).indices if 'season' in df else {}
        if module!='production':return
        self.groups=df.groupby(['kind','period','well'],sort=False).indices
        self.buckets={};self.colors={};self.periods={}
        from .config import COLORS
        for kind,part in df.groupby('kind',sort=False):
            self.periods[kind]=part.period.drop_duplicates().tolist()
            self.colors[kind]={p:COLORS[i%len(COLORS)] for i,p in enumerate(part.groupby('period').date.max().sort_values(ascending=False).index)}
            for period,bucket in part.groupby('period',sort=False):
                lo,hi=bucket.date.min(),bucket.date.max()
                if (hi-lo).days>3660:
                    self.buckets[(kind,period)]=None
                    continue
                calendar=pd.date_range(lo,hi)
                cumulative=bucket.groupby('date').q.sum().reindex(calendar,fill_value=0).cumsum()/1e6
                self.buckets[(kind,period)]=(calendar,cumulative.to_numpy(),bucket.well.drop_duplicates().tolist())
        tmp=df[['kind','well','period','q']].copy()
        tmp['positive']=tmp.q.gt(0);tmp['zero']=tmp.q.eq(0)
        self.stats=tmp.groupby(['kind','well','period']).agg(total=('q','sum'),active=('positive','sum'),zero=('zero','sum'),records=('q','size'))

    def __deepcopy__(self,memo):
        # Read-only after construction. pandas>=2.1 deep-copies DataFrame.attrs on every derived frame
        # (iloc, merge, ...), which copied the whole index each time: minutes on a million rows.
        return self


def index_for(df):
    value=df.attrs.get('_atlas_index')
    return value if value is not None and value.owner==id(df) else None


def select_wells(df,wells):
    index=index_for(df)
    if index is None:return df[df.well.isin(wells)].copy()
    parts=[index.wells[w] for w in dict.fromkeys(wells) if w in index.wells]
    positions=np.sort(np.concatenate(parts)) if parts else np.array([],dtype=int)
    return df.iloc[positions].copy()


def compact_strings(df,min_rows=20000):
    """Повторяющиеся строки (файл, лист, сезон, группа, скважина…) хранить одним объектом на значение.

    Тип колонок остаётся object, значения и пропуски те же — код расчётов не замечает разницы, а память
    на миллионе строк уменьшается в разы (каждая ячейка иначе — отдельная строка Python). Пропуск None становится NaN — для pandas это одно и то же."""
    if len(df)<min_rows:return df
    for column in df.columns:
        values=df[column]
        if values.dtype!=object:continue
        codes,uniques=pd.factorize(values)
        if len(uniques)*2>len(values):continue
        df[column]=pd.Categorical.from_codes(codes,pd.Index(uniques,dtype=object)).astype(object)
    return df


def memory_bytes(df,sample=2000):
    """Approximate ``memory_usage(deep=True)``: text columns are measured on an even sample of rows.

    The exact deep count walks every string (seconds per million rows) and is only shown as a rough figure."""
    total=int(df.memory_usage(index=True,deep=False).sum())
    if len(df)<=sample:return int(df.memory_usage(index=True,deep=True).sum())
    rows=np.linspace(0,len(df)-1,sample).astype(int)
    part=df.iloc[rows]
    for column in df.columns:
        if df[column].dtype==object:
            total+=int((part[column].memory_usage(index=False,deep=True)-part[column].memory_usage(index=False,deep=False))*len(df)/sample)
    return total


def prepare_table(raw,module,settings,token):
    d=exclusions.apply({module:raw},settings)[module]
    # Never attach mutable metadata to the raw snapshot shared with other sessions.
    d=d.copy(deep=False)
    if module=='production':
        from atlas.engine.modules.production import period_rule,periods_for
        d=periods_for(d,settings)
        d.attrs['_atlas_period_rule']=period_rule(settings)
        if settings.get('peak_windows') or settings.get('auto_peaks'):
            from atlas.engine.modules.seasons import peaks_for
            d.attrs['_atlas_peaks']=peaks_for(d,settings)
    d.attrs['_atlas_token']=token;d.attrs['_atlas_full_rows']=len(d)
    d.attrs['_atlas_index']=FrameIndex(d,module)
    return d


class Project:
    def __init__(self,root,pid,snapshot,tables):
        self.path=Path(root)/'projects'/pid/'snapshots'/str(snapshot)
        self.names=tuple(tables);self.token=signature([root,pid,snapshot]);self.lock=threading.RLock()
        self._raw={};self._views=OrderedDict();self._catalog=None
        self._memory={};self.disk_reads=0;self.view_builds=0;self.view_hits=0;self._ram_signature=None;self._estimated=None

    def raw(self,module):
        with self.lock:
            if module not in self._raw:
                d=compact_strings(pd.read_parquet(self.path/(module+'.parquet')));self.disk_reads+=1
                self._raw[module]=exclusions.identify(d,module,copy=False)     # d is a fresh private read
                self._memory[id(self._raw[module])]=memory_bytes(self._raw[module])
            return self._raw[module]

    def prepared(self,module,settings,fast=True):
        from atlas.engine.modules.production import period_rule
        relevant={'excluded_points':{k:v for k,v in settings.get('excluded_points',{}).items() if v.get('module')==module},
                  'period_rule':period_rule(settings) if module=='production' else None}
        if module=='production':
            relevant.update(season_start=settings.get('season_start',11),season_end=settings.get('season_end',4))
            relevant.update({k:settings[k] for k in ('auto_seasons','season_gap_days','season_rate_share','season_schedule','peak_windows','auto_peaks','peak_factor') if k in settings})
        key=(module,signature(relevant))
        with self.lock:
            if fast and key in self._views:
                self.view_hits+=1;self._views.move_to_end(key);return self._views[key]
            d=prepare_table(self.raw(module),module,relevant,self.token+':'+key[1]+':'+module);self.view_builds+=1
            if fast:
                self._views[key]=d
                # Keep current and one previous view PER MODULE; export without exclusions
                # must never evict production merely because four other modules were viewed.
                module_keys=[k for k in self._views if k[0]==module]
                for stale in module_keys[:-2]:self._views.pop(stale)
            return d

    def estimate_peak_bytes(self):
        if self._estimated is None:
            import pyarrow.parquet as pq
            rows=0;encoded=0
            for module in self.names:
                metadata=pq.ParquetFile(self.path/(module+'.parquet')).metadata
                rows+=metadata.num_rows
                encoded+=sum(metadata.row_group(i).total_byte_size for i in range(metadata.num_row_groups))
            # Conservative estimate: Python strings/IDs, prepared views and indices.
            # It is an estimate, not a measurement of process RSS.
            self._estimated=rows*768+encoded*3
        return self._estimated

    def preload(self,settings,budget_bytes=None):
        """Pin the entire active snapshot and current module views in server RAM."""
        if budget_bytes is not None and self.estimate_peak_bytes()>budget_bytes:return False
        state=signature([settings.get('excluded_points',{}),settings.get('season_start',11),settings.get('season_end',4)])
        if self._ram_signature==state:return True
        for module in self.names:self.prepared(module,settings)
        self._ram_signature=state
        return True

    def diagnostics(self):
        return {'loaded':list(self._raw),'modules':len(self.names),'raw_bytes':sum(self._memory.values()),
                'views':len(self._views),'disk_reads':self.disk_reads,'view_builds':self.view_builds,'view_hits':self.view_hits}

    def release(self):
        with self.lock:
            self._raw.clear();self._views.clear();self._memory.clear();self._catalog=None;self._ram_signature=None
            from atlas.engine.modules.well_analysis import cached_dataset,cached_analysis
            cached_dataset.clear();cached_analysis.clear()
            cache=chart_cache()
            with cache['lock']:
                for key in list(cache['entries']):
                    if key[1].startswith(self.token):
                        _,size=cache['entries'].pop(key);cache['bytes']-=size

    def catalog(self):
        """Read only small metadata columns, without loading measurement modules."""
        with self.lock:
            if self._catalog is not None:return self._catalog
            import pyarrow.parquet as pq
            entries={};mapping={};allw=set()
            for module in sorted(self.names,key=lambda m:m=='production'):      # группа из эксплуатации — главная: обрабатывается последней
                path=self.path/(module+'.parquet');columns=pq.ParquetFile(path).schema.names
                d=self._raw[module] if module in self._raw else pd.read_parquet(path,columns=[c for c in ('well','group','subgroup','date') if c in columns])
                wells=d.well.drop_duplicates().tolist() if 'well' in d else []
                allw.update(wells)
                entries[module]={'rows':len(d),'wells':wells,'start':d.date.min() if 'date' in d else None,'end':d.date.max() if 'date' in d else None}
                if 'well' in d and 'group' in d:
                    if 'subgroup' not in d:d['subgroup']=''
                    for row in d[['well','group','subgroup']].drop_duplicates('well',keep='last').itertuples(index=False):
                        if row.group!='Без группы' or row.well not in mapping:mapping[row.well]={'group':row.group,'subgroup':row.subgroup}
            self._catalog={'modules':entries,'mapping':mapping,'wells':list(allw)}
            return self._catalog


class Frames(Mapping):
    def __init__(self,project,settings=None,fast=True):
        self.project=project;self.settings=settings;self.fast=fast;self._held={}
    def __iter__(self):return iter(self.project.names)
    def __len__(self):return len(self.project.names)
    def __getitem__(self,module):
        if module not in self.project.names:raise KeyError(module)
        if module not in self._held:self._held[module]=self.project.raw(module) if self.settings is None else self.project.prepared(module,self.settings,self.fast)
        return self._held[module]


@cache_resource(max_entries=1)
def project_data(root,pid,snapshot,tables):
    return Project(root,pid,snapshot,tables)


def context(root,pid,manifest,fast=True):
    project=project_data(str(root),pid,manifest.get('snapshot'),tuple(manifest['tables']))
    return project,Frames(project),Frames(project,manifest['settings'],fast)


@cache_resource()
def chart_cache():
    return {'lock':threading.RLock(),'entries':OrderedDict(),'bytes':0,'hits':0,'misses':0}


def cached_chart(builder):
    @wraps(builder)
    def wrapped(df,*args,**kwargs):
        token=df.attrs.get('_atlas_token') if index_for(df) is not None else None
        if token is None:token=hashlib.sha256(pd.util.hash_pandas_object(df,index=True).values.tobytes()+str(list(df.columns)).encode('utf8')).hexdigest()
        def freeze(value):
            if isinstance(value,pd.DataFrame):
                return ('frame',hashlib.sha256(pd.util.hash_pandas_object(value,index=True).values.tobytes()+str(list(value.columns)).encode()).hexdigest())
            if isinstance(value,dict):return tuple(sorted((k,freeze(v)) for k,v in value.items()))
            if isinstance(value,(list,tuple)):return tuple(freeze(v) for v in value)
            if isinstance(value,set):return tuple(sorted(freeze(v) for v in value))
            return value
        key=(builder.__name__,token,freeze(args),freeze(kwargs));cache=chart_cache()
        with cache['lock']:
            found=cache['entries'].get(key)
            if found is None:
                fig=builder(df,*args,**kwargs);size=len(fig.to_json().encode('utf8'))
                cache['misses']+=1
                if size<=64*1024**2:
                    cache['entries'][key]=(fig,size);cache['bytes']+=size
                    while len(cache['entries'])>48 or cache['bytes']>64*1024**2:
                        _,(_,old)=cache['entries'].popitem(last=False);cache['bytes']-=old
            else:
                fig=found[0];cache['hits']+=1;cache['entries'].move_to_end(key)
            # Screen styling never mutates the shared original.
            return clone_figure(fig)
    return wrapped


def clone_figure(fig):
    """Copy already validated Plotly 5.24 objects without revalidating every point.

    This relies on the pinned Plotly object state. Copy parent links with a memo
    so the clone stays independent, including trace/layout callbacks and arrays.
    """
    clone=object.__new__(type(fig))
    clone.__dict__=copy.deepcopy(fig.__dict__,{id(fig):clone})
    return clone


def cached_analysis_chart(builder):
    @wraps(builder)
    def wrapped(analysis,name,settings=None):
        token=analysis.get('_cache_token')
        if token is None:return builder(analysis,name,settings)
        key=(builder.__module__+'.'+builder.__name__,token,name,signature(settings or {}),signature(analysis.get('gdi_raw',pd.DataFrame()).to_json(date_format='iso')) if name=='gdi' else '');cache=chart_cache()
        with cache['lock']:
            found=cache['entries'].get(key)
            if found:
                cache['hits']+=1;cache['entries'].move_to_end(key);return clone_figure(found[0])
            fig=builder(analysis,name,settings);size=len(fig.to_json().encode('utf8'));cache['misses']+=1
            if size<=64*1024**2:
                cache['entries'][key]=(fig,size);cache['bytes']+=size
                while len(cache['entries'])>48 or cache['bytes']>64*1024**2:
                    _,(_,old)=cache['entries'].popitem(last=False);cache['bytes']-=old
            return clone_figure(fig)
    return wrapped
