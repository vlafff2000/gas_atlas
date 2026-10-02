"""Persistent, reversible exclusions; source tables are never destructively edited."""
import datetime as dt
import numpy as np
import pandas as pd

KEYS={'pressure_match':['object','scenario','well','date','fact','model'],'production':['kind','well','date'],
      'gdi':['well','date','method','study','q','dp2'],
      'response':['well','date','horizon'], 'object_pressure':['date'],
      'operations':['well','date','kind'], 'water':['well','date'], 'bottom':['well','date'],
      'construction':['well','date','element','top_m','bottom_m','diameter_mm']}

def _text(series):
    """str() once per distinct value; hashes identically to series.astype(str) but is far cheaper on millions of rows."""
    codes,uniques=pd.factorize(series.fillna(''))
    categories=pd.Index([str(u) for u in uniques],dtype=object)
    if not categories.is_unique:return series.fillna('').astype(str)
    return pd.Categorical.from_codes(codes,categories)

def identify(df,module):
    d=df.copy()
    if d.empty:
        d['_point_id']=pd.Series(dtype=str)
        return d
    values=pd.DataFrame(index=d.index)
    for field in KEYS[module]:
        if field=='date': values[field]=pd.to_datetime(d[field]).astype('datetime64[ns]')
        elif field in ('q','dp2','top_m','bottom_m','diameter_mm'): values[field]=pd.to_numeric(d[field],errors='coerce').astype(float) if field in d else np.nan
        else: values[field]=_text(d[field]) if field in d else ''
    hashed=pd.util.hash_pandas_object(values,index=False)
    if module=='gdi':
        # Independent duplicate measurements retain their own reversible identity.
        values['_occurrence']=hashed.groupby(hashed).cumcount()
        hashed=pd.util.hash_pandas_object(values,index=False)
    d['_point_id']=module+':'+hashed.astype(str)
    return d

def identify_frames(frames):
    return {module:identify(d,module) for module,d in frames.items()}

def point_id(module,identifier,metric=None):
    return identifier+':'+(metric or 'level') if module=='response' else identifier

def apply(frames,settings):
    excluded=settings.get('excluded_points',{})
    if not excluded and all('_point_id' in d for d in frames.values()):
        return dict(frames)
    out={}
    for module,source in frames.items():
        d=source.copy()
        if '_point_id' not in d: d=identify(d,module)
        if module=='response':
            for metric in ('level','pressure'):
                if metric in d:
                    mask=(d['_point_id']+':'+metric).isin(excluded)
                    d.loc[mask,metric]=np.nan
        elif module=='production':
            d['_excluded']=d['_point_id'].isin(excluded)
            d.loc[d['_excluded'],'q']=np.nan
        else: d=d.loc[~d['_point_id'].isin(excluded)].copy()
        out[module]=d
    return out

def entry(frames,module,identifier,metric=None,reason='Исключено вручную'):
    metric=metric or ('level' if module=='response' else 'pressure' if module=='object_pressure' else 'q')
    d=frames.get(module,pd.DataFrame())
    base=identifier.rsplit(':',1)[0] if module=='response' else identifier
    if d.empty: return None
    rows=d[d['_point_id'].eq(base)]
    if rows.empty: return None
    r=rows.iloc[0]
    if module=='response' and (metric not in r or pd.isna(r[metric])): return None
    result={'id':identifier,'module':module,'metric':metric,'reason':reason,
            'excluded_utc':dt.datetime.now(dt.timezone.utc).isoformat()}
    for field in ('well','date','kind','horizon','method','study','q','dp2','level','pressure','file','sheet','_row',
                  'work_hours','gas_volume_m3','water_volume_m3','water_rate','water_flag','bottom_m','tool_diameter_mm','element','top_m','diameter_mm','comment','fact','model','scenario','object','fond'):
        if field not in r: continue
        value=r[field]
        if pd.isna(value): value=None
        elif isinstance(value,pd.Timestamp): value=value.isoformat()
        elif isinstance(value,np.generic): value=value.item()
        result[field]=value
    return result

def journal(settings):
    return pd.DataFrame(list(settings.get('excluded_points',{}).values()))

def public_table(d):
    return d.drop(columns=[c for c in d if c.startswith('_point') or c=='_excluded'],errors='ignore')
