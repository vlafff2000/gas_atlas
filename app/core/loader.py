"""Import with provenance, explicit units and rejection diagnostics; no formula execution."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import csv
import io
import re
import zipfile
from itertools import islice
import numpy as np
import pandas as pd
import openpyxl
from .well_import import ALIASES as WELL_ALIASES, REQUIRED as WELL_REQUIRED, detect as detect_well, normalize as normalize_well

ALIASES = {
    'well': ['скважина', 'скв', '№скважины', 'номерскважины', '№скв', 'well', 'wellid', 'номер'],
    'date': ['дата', 'датагди', 'датаисследования', 'датазамера', 'date', 'datetime'],
    'q': ['q', 'qгаза', 'qгазатысм3сут', 'расходгаза', 'расход', 'дебит', 'суточныйрасходгаза', 'суточныйрасход', 'flow'],
    'p_res': ['рпл', 'pпл', 'ppl', 'p_res', 'пластовоедавление','пластовоедавлениеобъекта','давлениеобъекта', 'рпласт', 'рплатм'],
    'p_bh': ['рзаб', 'pзаб', 'рз', 'pз', 'pzab', 'p_bh', 'забойноедавление'],
    'dp2': ['рпл2рз2', 'рпл2рзаб2', 'δp2', 'δр2', 'dp2', 'deltap2', 'дельтар2'],
    'horizon': ['горизонт', 'пласт', 'horizon', 'formation'],
    'level': ['уровень', 'уровеньжидкости', 'уровеньчисло', 'нуст', 'уст', 'ну', 'level'],
    'pressure': ['рплпривед', 'рплприв', 'приведенноедавление', 'pressure', 'рплприведенное'],
    'group': ['группа', 'источник', 'group', 'source'],
    'subgroup': ['подгруппа', 'номерподгруппы', 'subgroup'],
    'season': ['сезон', 'season'], 'year': ['год', 'year'],
    'kind': ['тип', 'типданных', 'режим', 'kind'],
    'method': ['метод', 'методисследования', 'method'],
    'study': ['исследование', 'номерисследования', 'study', 'studyid'],
    'a_db': ['a', 'а', 'a_db'], 'b_db': ['b', 'в', 'b_db'],
    'plan_volume': ['план', 'плановыйобъем', 'объемпоплану', 'планмлнм3', 'планмлнм', 'planvolume', 'plan'],
}
ALIASES.update(WELL_ALIASES)
ALIASES['date']+=['Дата конструкции','Дата замера забоя']
ALIASES['method']+=['Метод замера']

def norm(v):
    return re.sub(r'[^\wδ]', '', str(v or '').lower().replace('ё', 'е').replace('²', '2').replace('³', '3')).replace('_', '')

def column_map(labels):
    result = {}
    normalized = [norm(v) for v in labels]
    for field, aliases in ALIASES.items():
        aliases = [norm(x) for x in aliases]
        matches = [i for i, n in enumerate(normalized) if n in aliases]
        if not matches and field in ('q', 'level', 'p_res', 'p_bh', 'pressure', 'plan_volume')+tuple(WELL_ALIASES):
            # Recognize unit-bearing labels, without confusing Рпл with Рпл привед.
            for i, value in enumerate(labels):
                base = re.split(r'[,\[(]', str(value))[0]
                if norm(base) in aliases:
                    matches.append(i)
            if not matches and field in ('q','level'):
                matches = [i for i,n in enumerate(normalized) if any(n.startswith(a) for a in aliases if len(a)>4)]
        if len(matches) > 1:
            raise ValueError(f'Несколько колонок для поля «{field}»: {[labels[i] for i in matches]}. Оставьте одну.')
        if matches:
            result[field] = matches[0]
    if 'date' not in result:
        # «Месяц» — дата только в плане; если есть обычная колонка даты, «Месяц» остаётся отдельным столбцом.
        month = [i for i, n in enumerate(normalized) if n == 'месяц']
        if len(month) == 1:
            result['date'] = month[0]
    if 'q' in result and result.get('water_rate')==result['q']:
        # The legacy broad "Расход..." alias must not turn water into gas.
        result.pop('q')
    return result

def numeric(s, level=False):
    s = s.astype('string').str.strip().str.replace(r'[\s\u00a0\u202f]', '', regex=True).str.replace(',', '.', regex=False)
    if level:
        # A single number and an optional unit. Ranges and prose are not concatenated.
        s = s.str.extract(r'^([+-]?(?:\d+(?:\.\d*)?|\.\d+))(?:м|m|метр(?:а|ов)?)?$', expand=False)
    return pd.to_numeric(s, errors='coerce').astype(float).replace([np.inf,-np.inf],np.nan)

def dates(s):
    text = s.astype('string').str.strip()
    result = pd.Series(pd.NaT, index=s.index, dtype='datetime64[ns]')
    serial = text.str.fullmatch(r'\d{5}(?:\.\d+)?', na=False)
    if serial.any():
        # pandas 2.0 needs a NumPy numeric dtype for a non-Unix origin.
        result.loc[serial] = pd.to_datetime(pd.to_numeric(text[serial]).astype('float64'), unit='D', origin='1899-12-30', errors='coerce')
    iso = text.str.match(r'^\d{4}-\d{1,2}-\d{1,2}', na=False) & ~serial
    result.loc[iso] = pd.to_datetime(text[iso], errors='coerce', format='mixed')
    other = ~(serial | iso)
    result.loc[other] = pd.to_datetime(text[other], errors='coerce', dayfirst=True, format='mixed')
    return result.dt.normalize()

def well_ids(s):
    return s.fillna('').astype(str).str.strip().str.replace(r'\.0$', '', regex=True)

def rate_unit(label,fallback):
    label=str(label).lower().replace('³','3').replace('^','')
    if 'тыс' in label: return 'тыс. м³/сут'
    if re.search(r'(м|m)\s*3\s*/\s*(сут|day|d)',label): return 'м³/сут'
    return fallback

@dataclass
class ImportResult:
    frames: dict = field(default_factory=dict)
    counts: dict = field(default_factory=dict)
    issues: list = field(default_factory=list)
    rejected: int = 0
    warnings: int = 0

    def issue(self, file, sheet, row, reason, level='ошибка'):
        if level == 'ошибка': self.rejected += 1
        else: self.warnings += 1
        if len(self.issues) < 2000:
            self.issues.append({'Файл':file,'Лист':sheet,'Строка':int(row),'Уровень':level,'Причина':reason})

def iter_sheets(path, chunk_size=50000, encoding='auto', delimiter='auto'):
    from .tabular import iter_tables
    yield from iter_tables(path,encoding,delimiter)


def detect_layout(head,module='auto'):
    detected=None;mapping={};wide=False;header=-1
    for i,row in enumerate(head):
        if not any(v is not None and str(v).strip() for v in row): continue
        mapping=column_map(row)
        if {'well','date'}<=mapping.keys() and (module in WELL_REQUIRED or module=='auto' and detect_well(mapping)):
            detected=module if module in WELL_REQUIRED else detect_well(mapping);header=i;break
        if module in ('groups','subgroups') and 'well' not in mapping and i==0 and len(row)>=2:
            mapping={'well':0, 'subgroup' if module=='subgroups' else 'group':1}
            if module=='groups' and len(row)>2: mapping['subgroup']=2
            detected='groups';header=-1;break
        if module in ('auto','plan') and 'well' not in mapping and {'group','date','plan_volume'}<=mapping.keys():
            detected='plan';header=i;break
        if module in ('auto','object_pressure') and 'well' not in mapping and 'date' in mapping and ('p_res' in mapping or 'pressure' in mapping):
            mapping['pressure']=mapping.pop('p_res') if 'p_res' in mapping else mapping['pressure']
            detected='object_pressure';header=i;break
        if {'well','date'} <= mapping.keys():
            if module != 'auto': detected=module
            elif 'horizon' in mapping and ('level' in mapping or 'pressure' in mapping): detected='response'
            elif 'q' in mapping and ('dp2' in mapping or {'p_res','p_bh'}<=mapping.keys()): detected='gdi'
            elif 'q' in mapping: detected='production'
            if detected: header=i; break
        if 'well' in mapping and ('group' in mapping or 'subgroup' in mapping) and 'date' not in mapping:
            detected='groups'; header=i; break
        if module in ('auto','production') and i+1<len(head) and len(row)>1:
            if pd.notna(dates(pd.Series([head[i+1][0]]))[0]) and all(re.fullmatch(r'[\w.-]+',str(v).strip()) for v in row[1:] if v is not None):
                # Only a blank/date corner can be a matrix header.
                if norm(row[0]) in ('','дата','date'):
                    detected='production'; wide=True; header=i; break
    return {'module':detected,'mapping':mapping if detected else {},'wide':wide,'header':header if detected else 0}

def load_file(path, module='auto', production_kind='withdrawal', production_unit='м³/сут',
              gdi_unit='тыс. м³/сут', progress=None, chunk_size=50000, sheet_options=None, encoding='auto', delimiter='auto'):
    result = ImportResult(); collected = {}; filename=Path(path).name
    for sheet, iterator in iter_sheets(path,encoding=encoding,delimiter=delimiter):
        iterator=iter(iterator); head=list(islice(iterator,31)); detected=None; mapping={}; wide=False; header=-1
        if sheet=='Инструкция' and head and head[0] and str(head[0][0]).startswith('Заполните первый лист своими данными'):continue
        spec=(sheet_options or {}).get(sheet)
        if spec is not None:
            if not spec.get('enabled',True):continue
            detected=spec.get('module');mapping=spec.get('mapping',{});wide=spec.get('wide',False);header=spec.get('header',0)
            if detected=='subgroups':detected='groups'
            target_width=max(len(spec.get('names',{})),max((len(r) for r in head),default=0))
            head=[list(r)+[None]*(target_width-len(r)) for r in head]
            if spec.get('names') and header>=0:
                head[header]=[spec['names'].get(str(j),v) for j,v in enumerate(head[header])]
        else:
            layout=detect_layout(head,module);detected=layout['module'];mapping=layout['mapping'];wide=layout['wide'];header=layout['header']
        if detected is None:
            result.issue(filename,sheet,1,'Таблица не распознана. Нужны заголовки из шаблона.', 'предупреждение'); continue
        required={**WELL_REQUIRED,'production':{'well','date','q'},'gdi':{'well','date','q'},'response':{'well','date','horizon'},'object_pressure':{'date','pressure'},'plan':{'group','date','plan_volume'},'groups':{'well'}}[detected]
        if not wide and not required<=mapping.keys():
            raise ValueError(f'{sheet}: не найдены поля {", ".join(sorted(required-mapping.keys()))}.')
        if detected=='gdi' and not ('dp2' in mapping or {'p_res','p_bh'}<=mapping.keys()):
            raise ValueError(f'{sheet}: для ГДИ нужны Рпл и Рзаб либо готовое ΔP².')
        from itertools import chain
        remaining=chain(head[header+1:],iterator); row_offset=header+2
        while True:
            rows=list(islice(remaining,chunk_size))
            if not rows: break
            width=len(head[max(0,header)]); rows=[list(r[:width])+[None]*max(0,width-len(r)) for r in rows]
            raw=pd.DataFrame(rows); nonempty=raw.notna().any(axis=1)&raw.fillna('').astype(str).apply(lambda c:c.str.strip()).ne('').any(axis=1)
            raw=raw[nonempty]
            if raw.empty: row_offset+=len(rows); continue
            if wide:
                if spec and 'date' not in mapping:raise ValueError('Выберите колонку даты для матрицы.')
                datecol=spec.get('datecol',0) if spec else 0
                wellcols=spec.get('wellcols',[j for j in range(width) if j!=datecol]) if spec else list(range(1,width))
                raw=raw[[datecol]+wellcols].copy()
                raw.columns=['date']+[str(head[header][j] or '').strip() for j in wellcols]
                raw['_row']=raw.index+row_offset
                raw=raw.melt(id_vars=['date','_row'],var_name='well',value_name='q')
                raw=raw[raw.q.notna() & raw.q.astype(str).str.strip().ne('') & raw.well.ne('')].reset_index(drop=True)
                df=raw.copy()
            else:
                df=pd.DataFrame({k:raw[i] for k,i in mapping.items()}); df['_row']=raw.index+row_offset
            reasons=pd.Series('',index=df.index)
            if detected not in ('object_pressure','plan'):
                df['well']=well_ids(df.well)
                reasons.loc[df.well.eq('')]='Не указан номер скважины'
            if detected!='groups':
                df['date']=dates(df.date); reasons.loc[df.date.isna()]='Некорректная или пустая дата'
            supplied_level=df['level'].notna() & df['level'].astype(str).str.strip().ne('') if 'level' in df else pd.Series(False,index=df.index)
            supplied_pressure=df['pressure'].notna() & df['pressure'].astype(str).str.strip().ne('') if 'pressure' in df else pd.Series(False,index=df.index)
            if detected in WELL_REQUIRED:
                for col in ('p_res','p_bh'):
                    if col in df:
                        supplied=df[col].notna()&df[col].astype(str).str.strip().ne('')
                        reasons.loc[supplied&numeric(df[col]).isna()]='Некорректное давление в поле '+col
            for col in ('q','p_res','p_bh','dp2','a_db','b_db','pressure','level','plan_volume'):
                if col in df: df[col]=numeric(df[col],level=col=='level')
            if detected in WELL_REQUIRED:
                df=normalize_well(df,detected,reasons,numeric)
                for col in ('gas_volume_m3','water_volume_m3','water_rate'):
                    if col in mapping and col in df and 'тыс' in str(head[header][mapping[col]]).lower():df[col]*=1000
                if detected=='operations':
                    kinds=df.get('kind',pd.Series(production_kind,index=df.index)).fillna(production_kind).astype(str).str.strip()
                    reasons.loc[~kinds.str.contains('отбор|withdraw|закач|inject|^$',case=False,regex=True)]='Тип эксплуатации: отбор или закачка'
                    df['kind']=kinds.apply(lambda x:'injection' if re.search('закач|inject',x,re.I) else production_kind if not x else 'withdrawal')
                    for col in ('p_res','p_bh'):
                        reasons.loc[df[col].lt(0)]='Давление не может быть отрицательным'
            if detected=='production':
                unit=production_unit
                label=str(head[header][mapping['q']]) if not wide else ''
                unit=rate_unit(label,unit)
                df['q']=df.q*(1000 if unit=='тыс. м³/сут' else 1)
                reasons.loc[~np.isfinite(df.q)|df.q.lt(0)]='Расход должен быть конечным неотрицательным числом'
                named='injection' if re.search('закач|inject',sheet,re.I) else 'withdrawal' if re.search('отбор|withdraw',sheet,re.I) else production_kind
                df['kind']=df.get('kind',pd.Series('',index=df.index)).fillna('').astype(str).apply(lambda x:'injection' if re.search('закач|inject',x,re.I) else 'withdrawal' if re.search('отбор|withdraw',x,re.I) else named)
            elif detected=='gdi':
                unit=gdi_unit
                label=str(head[header][mapping['q']])
                unit=rate_unit(label,unit)
                df['q']=df.q/(1000 if unit=='м³/сут' else 1)
                if unit=='м³/сут':
                    if 'a_db' in df: df['a_db']*=1000
                    if 'b_db' in df: df['b_db']*=1_000_000
                reasons.loc[~np.isfinite(df.q)|df.q.lt(0)]='Q должен быть конечным неотрицательным числом'
                if {'p_res','p_bh'}<=set(df):
                    calculated=df.p_res**2-df.p_bh**2
                    validp=df.p_res.ge(0)&df.p_bh.ge(0)&calculated.ge(0)
                    if 'dp2' in df:
                        inconsistent=df.dp2.notna()&validp&~np.isclose(df.dp2,calculated,rtol=.001,atol=.01)
                        for ix in df.index[inconsistent]: result.issue(filename,sheet,df.loc[ix,'_row'],'ΔP² отличается от Рпл² − Рзаб²; использован расчет по давлениям.','предупреждение')
                        df.loc[validp,'dp2']=calculated[validp]
                    else: df['dp2']=calculated
                    both=df.p_res.notna()&df.p_bh.notna()
                    reasons.loc[both&~validp]='Проверьте давления: Рпл ≥ Рзаб ≥ 0'
                reasons.loc[~np.isfinite(df.dp2)|df.dp2.lt(0)]='Нет корректного ΔP² или пары давлений'
            elif detected=='response':
                df['horizon']=df.horizon.fillna('').astype(str).str.strip()
                reasons.loc[df.horizon.eq('')]='Не указан горизонт'
                if 'level' not in df:df['level']=np.nan
                if 'pressure' not in df:df['pressure']=np.nan
                reasons.loc[df.level.isna() & df.pressure.isna()]='Не распознаны уровень и давление: требуется хотя бы один показатель'
                reasons.loc[supplied_level & df.level.isna()]='Уровень не распознан: допустимо число или число с единицей «м»'
                reasons.loc[supplied_pressure & df.pressure.isna()]='Некорректное давление'
                reasons.loc[df.pressure.lt(0)]='Давление не может быть отрицательным'
            elif detected=='object_pressure':
                reasons.loc[df.pressure.isna() | df.pressure.lt(0)]='Некорректное или отрицательное давление объекта'
            elif detected=='plan':
                # План хранится в млн м³; единицу берём из заголовка колонки («млрд», «тыс.» — пересчёт).
                label=str(head[header][mapping['plan_volume']]).lower().replace('³','3')
                df['plan_volume']=df.plan_volume*(1000 if 'млрд' in label else 0.001 if 'тыс' in label else 1)
                reasons.loc[df.plan_volume.isna()|~np.isfinite(df.plan_volume)|df.plan_volume.lt(0)]='План должен быть конечным неотрицательным числом'
                df['group']=df.group.fillna('').astype(str).str.strip()
                reasons.loc[df.group.eq('')]='Не указана группа'
                named='injection' if re.search('закач|inject',sheet,re.I) else 'withdrawal' if re.search('отбор|withdraw',sheet,re.I) else production_kind
                df['kind']=df.get('kind',pd.Series('',index=df.index)).fillna('').astype(str).apply(lambda x:'injection' if re.search('закач|inject',x,re.I) else 'withdrawal' if re.search('отбор|withdraw',x,re.I) else named)
                df['date']=df.date.dt.to_period('M').dt.to_timestamp()
            for ix in df.index[reasons.ne('')]: result.issue(filename,sheet,df.loc[ix,'_row'],reasons.loc[ix])
            df=df[reasons.eq('')].copy()
            for col in ('group','subgroup','season','year','method','study'):
                if col not in df: df[col]=''
                df[col]=df[col].fillna('').astype(str).str.strip()
            df['group']=df['group'].replace('','Без группы')
            df['file']=filename; df['sheet']=sheet
            if not df.empty: collected.setdefault(detected,[]).append(df)
            row_offset+=len(rows)
            if progress: progress(sheet,row_offset-2)
    for name,frames in collected.items():
        result.frames[name]=pd.concat(frames,ignore_index=True); result.counts[name]=len(result.frames[name])
    if not result.frames and not result.issues:
        raise ValueError('Файл не содержит строк данных.')
    return result

def merge_frames(old, new, module, policy='new'):
    """No summing of duplicate daily values. GDI replacement is whole-study atomic."""
    if old is None or old.empty or policy=='replace': base=new.copy()
    elif module in ('gdi','construction'):
        keys=['well','date','method','study'] if module=='gdi' else ['well','date']
        old=old.copy(); new=new.copy()
        for c in keys:
            if c not in old: old[c]=''
            if c not in new: new[c]=''
        okeys=pd.MultiIndex.from_frame(old[keys]); nkeys=pd.MultiIndex.from_frame(new[keys])
        base=pd.concat([old[~okeys.isin(nkeys)],new],ignore_index=True) if policy=='new' else pd.concat([old,new[~nkeys.isin(okeys)]],ignore_index=True)
    else: base=pd.concat([old,new] if policy=='new' else [new,old],ignore_index=True)
    keys={'production':['kind','well','date'],'response':['well','date','horizon'],
          'pressure_match':['object','scenario','well','date'],'groups':['well'],'object_pressure':['date'],'plan':['kind','group','date'],'gdi':['well','date','method','study','q','dp2'],
          'operations':['well','date','kind'],'water':['well','date'],'bottom':['well','date'],
          'construction':['well','date','element','top_m','bottom_m','diameter_mm']}[module]
    if module=='gdi': keys += [c for c in ('p_res','p_bh','a_db','b_db') if c in base]
    before=len(base); base=base.drop_duplicates(keys,keep='last').reset_index(drop=True)
    return base,before-len(base)
