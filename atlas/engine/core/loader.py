"""Import with provenance, explicit units and rejection diagnostics; no formula execution."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import csv
import datetime
import io
import re
import zipfile
from itertools import islice
import numpy as np
import pandas as pd
import openpyxl
from .config import NODATA
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
# Вынос воды по объекту (таблица без скважин): «Дата | Накопленный расход газа | Водный фактор нарастающий |
# Накопленная вода | Расход воды | Водный Фактор | Объем газа в пласте». Поля ищутся отдельно от общих ALIASES,
# чтобы «Расход воды» здесь не путался с расходом воды по скважине.
WATER_FACTOR_ALIASES = {
    'gas_cum': ['накопленныйрасходгаза', 'накопленныйотборгаза', 'накопленныйгаз'],
    'wf_cum': ['водныйфакторнарастающий', 'водныйфакторнакопленный', 'накопленныйводныйфактор'],
    'water_cum': ['накопленнаявода', 'накопленныйвыносводы', 'накопленныйобъемводы'],
    'water_day': ['расходводы', 'суточныйрасходводы', 'суточныйвынос'],
    'wf': ['водныйфактор', 'суточныйводныйфактор'],
    'gas_in_place': ['объемгазавпласте', 'запасгазавпласте', 'остаточныйобъемгаза'],
}
WATER_FACTOR_NEW = ('gas_cum', 'wf_cum', 'water_cum', 'wf', 'gas_in_place')

def water_factor_map(labels):
    """Колонки таблицы «вынос воды по объекту»; пусто, если это не она (нужны дата, объём газа в пласте и ещё одна колонка)."""
    base = [norm(re.split(r'[,\[(]', str(v))[0]) for v in labels]
    result = {}
    for field, aliases in WATER_FACTOR_ALIASES.items():
        hits = [i for i, n in enumerate(base) if n in aliases]
        if len(hits) == 1:
            result[field] = hits[0]
    dates = [i for i, n in enumerate(base) if n in ('дата', 'date')]
    if len(dates) == 1:
        result['date'] = dates[0]
    return result if {'date', 'gas_in_place'} <= result.keys() and len(result) >= 3 else {}
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

MONTHS={'январь':1,'января':1,'янв':1,'февраль':2,'февраля':2,'фев':2,'март':3,'марта':3,'мар':3,'апрель':4,'апреля':4,'апр':4,
        'май':5,'мая':5,'июнь':6,'июня':6,'июн':6,'июль':7,'июля':7,'июл':7,'август':8,'августа':8,'авг':8,
        'сентябрь':9,'сентября':9,'сен':9,'сент':9,'октябрь':10,'октября':10,'окт':10,'ноябрь':11,'ноября':11,'ноя':11,'нояб':11,
        'декабрь':12,'декабря':12,'дек':12}

def month_cell(v):
    """Ячейка заголовка плана-матрицы → (месяц, год | None) или None: дата, «05.2025», «2025-05», «Май», «Май 2025»."""
    if isinstance(v,(pd.Timestamp,datetime.date)):return (v.month,v.year) if pd.notna(v) else None
    if v is None or isinstance(v,(int,float)):return None
    t=str(v).strip().lower().replace('ё','е')
    m=re.fullmatch(r'(\d{1,2})[./](\d{4})',t)
    if m and 1<=int(m.group(1))<=12:return int(m.group(1)),int(m.group(2))
    m=re.fullmatch(r'(\d{4})-(\d{1,2})(?:-\d{1,2})?(?:\s+00:00:00)?',t)
    if m and 1<=int(m.group(2))<=12:return int(m.group(2)),int(m.group(1))
    m=re.fullmatch(r'([а-я]+)\.?\s*(\d{4})?\s*(?:г\.?|года)?',t)
    if m and m.group(1) in MONTHS:return MONTHS[m.group(1)],(int(m.group(2)) if m.group(2) else None)
    return None

def is_number(v):
    try:float(str(v).replace(',','.').replace('\xa0','').replace(' ',''));return v is not None and str(v).strip()!=''
    except ValueError:return False

def plan_matrix_months(labels,cols,title):
    """Месяц (первое число) для каждой колонки-месяца: {колонка: дата}. Год без указания берётся из заголовка таблицы,
    при переходе декабрь → январь год растёт."""
    found=[(j,month_cell(labels[j])) for j in cols]
    found=[(j,c) for j,c in found if c]
    year=next((int(y) for y in re.findall(r'(?<!\d)(20\d{2})(?!\d)',title)),None)
    out={};previous=0
    for j,(month,own) in found:
        if own is not None:year=own
        elif year is None:raise ValueError('В названиях месяцев нет года: добавьте его («Май 2025») или укажите в заголовке таблицы либо названии листа.')
        elif previous and month<previous:year+=1
        previous=month;out[j]=pd.Timestamp(year=year,month=month,day=1)
    return out

def numeric(s, level=False, keep_nodata=False):
    """Число из ячейки; условное «нет данных» (−999,25 и подобные) — пропуск, если не ``keep_nodata``."""
    s = s.astype('string').str.strip().str.replace(r'[\s\u00a0\u202f]', '', regex=True).str.replace(',', '.', regex=False)
    if level:
        # A single number and an optional unit. Ranges and prose are not concatenated.
        s = s.str.extract(r'^([+-]?(?:\d+(?:\.\d*)?|\.\d+))(?:м|m|метр(?:а|ов)?)?$', expand=False)
    out = pd.to_numeric(s, errors='coerce').astype(float).replace([np.inf,-np.inf],np.nan)
    return out if keep_nodata else out.mask(out.isin(NODATA))

def nodata(s):
    """Ячейки с условным «нет данных»."""
    return numeric(s, keep_nodata=True).isin(NODATA)

def date_order(s):
    """Порядок «д.м.г» в колонке: dmy (есть день > 12 первым), mdy (есть день > 12 вторым), mixed, ambiguous (не определить)."""
    parts = s.astype('string').str.strip().str.extract(r'^(\d{1,2})[./-](\d{1,2})[./-]\d{2,4}')
    first, second = (pd.to_numeric(parts[i], errors='coerce') for i in (0, 1))
    a, b = bool((first > 12).any()), bool((second > 12).any())
    return 'mixed' if a and b else 'dmy' if a else 'mdy' if b else 'ambiguous'

def dates(s, order=None):
    text = s.astype('string').str.strip()
    result = pd.Series(pd.NaT, index=s.index, dtype='datetime64[ns]')
    serial = text.str.fullmatch(r'\d{5}(?:\.\d+)?', na=False)
    if serial.any():
        # pandas 2.0 needs a NumPy numeric dtype for a non-Unix origin.
        result.loc[serial] = pd.to_datetime(pd.to_numeric(text[serial]).astype('float64'), unit='D', origin='1899-12-30', errors='coerce')
    iso = text.str.match(r'^\d{4}-\d{1,2}-\d{1,2}', na=False) & ~serial
    result.loc[iso] = pd.to_datetime(text[iso], errors='coerce', format='mixed')
    other = ~(serial | iso)
    result.loc[other] = pd.to_datetime(text[other], errors='coerce', dayfirst=order!='mdy', format='mixed')
    return result.dt.normalize()

def well_ids(s):
    return s.fillna('').astype(str).str.strip().str.replace(r'\.0$', '', regex=True)

RATE_TO_M3={'м³/сут':1,'тыс. м³/сут':1000,'млн м³/сут':10**6,'млрд м³/сут':10**9}
MPA_TO_KGF=10.197162129779
BAR_TO_KGF=1.0197162129779

def rate_unit(label,fallback):
    """Единица расхода из заголовка колонки («Q, млн м³/сут»); нет в заголовке — ``fallback``."""
    label=str(label).lower().replace('³','3').replace('^','')
    if 'млрд' in label: return 'млрд м³/сут'
    if 'млн' in label: return 'млн м³/сут'
    if 'тыс' in label: return 'тыс. м³/сут'
    if re.search(r'(м|m)\s*3\s*/\s*(сут|day|d)',label): return 'м³/сут'
    return fallback

def volume_factor(label):
    """Множитель объёма (в м³) по заголовку: «тыс.» → 1000, «млн» → 10⁶, «млрд» → 10⁹; без приставки — 1."""
    label=str(label).lower().replace('³','3')
    return 10**9 if 'млрд' in label else 10**6 if 'млн' in label else 1000 if 'тыс' in label else 1

def pressure_factor(label):
    """Множитель в кгс/см² по единице в заголовке колонки давления («Рпл, МПа», «Рзаб, бар»); None — единицы нет."""
    label=str(label).lower()
    if re.search(r'мпа|mpa',label): return MPA_TO_KGF
    if re.search(r'(?<![а-яa-z])(бар|bar)(?![а-яa-z])',label): return BAR_TO_KGF
    return None

@dataclass
class ImportResult:
    frames: dict = field(default_factory=dict)
    counts: dict = field(default_factory=dict)
    issues: list = field(default_factory=list)
    rejected: int = 0
    warnings: int = 0
    omitted: int = 0      # замечаний сверх лимита журнала
    by_header: dict = field(default_factory=dict)      # модуль -> колонки давления, уже пересчитанные по единице из заголовка

    def issue(self, file, sheet, row, reason, level='ошибка'):
        if level == 'ошибка': self.rejected += 1
        else: self.warnings += 1
        if len(self.issues) < 2000:
            self.issues.append({'Файл':file,'Лист':sheet,'Строка':int(row),'Уровень':level,'Причина':reason})
        else: self.omitted += 1

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
        if module in ('auto','water_factor') and 'well' not in mapping:
            wf_map=water_factor_map(row)
            if wf_map:
                mapping=wf_map;detected='water_factor';header=i;break
        if module in ('auto','plan') and sum(month_cell(v) is not None for v in row[1:])>=2 \
                and any(str(r[0] or '').strip() and any(is_number(v) for v in r[1:]) for r in head[i+1:i+4]):
            detected='plan';wide=True;mapping={'date':0};header=i;break       # матрица: группы в строках, месяцы в столбцах
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
        required={**WELL_REQUIRED,'production':{'well','date','q'},'gdi':{'well','date','q'},'response':{'well','date','horizon'},'object_pressure':{'date','pressure'},'plan':{'group','date','plan_volume'},'water_factor':{'date','gas_in_place'},'groups':{'well'}}[detected]
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
            if wide and detected=='plan':
                datecol=spec.get('datecol',0) if spec else 0
                cols=spec.get('wellcols',[j for j in range(width) if j!=datecol]) if spec else [j for j in range(width) if j!=datecol]
                title=' '.join(str(c) for r in head[:max(0,header)] for c in r if c is not None)+' '+sheet+' '+filename
                months=plan_matrix_months(head[header],cols,title)
                if not months:raise ValueError(f'{sheet}: в строке заголовков нет месяцев.')
                raw=raw[[datecol]+list(months)].copy();raw.columns=['group']+list(months.values());raw['_row']=raw.index+row_offset
                raw['group']=raw.group.fillna('').astype(str).str.strip()
                raw=raw[raw.group.ne('')&~raw.group.str.fullmatch(r'(?i)всего|итого|суммарно|сумма')]
                df=raw.melt(id_vars=['group','_row'],var_name='date',value_name='plan_volume')
                df=df[df.plan_volume.notna()&df.plan_volume.astype(str).str.strip().ne('')].reset_index(drop=True);df['date']=pd.to_datetime(df.date)
                low=title.lower()
                if re.search('закач|inject',low) and not re.search('отбор|withdraw',low):df['kind']='injection'
                elif re.search('отбор|withdraw',low) and not re.search('закач|inject',low):df['kind']='withdrawal'
            elif wide:
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
            if detected not in ('object_pressure','plan','water_factor'):
                df['well']=well_ids(df.well)
                reasons.loc[df.well.eq('')]='Не указан номер скважины'
            if detected!='groups':
                order=date_order(df.date); df['date']=dates(df.date,order); reasons.loc[df.date.isna()]='Некорректная или пустая дата'
                if order=='mdy': result.issue(filename,sheet,max(header,0)+1,'Даты прочитаны как месяц/день/год: в колонке есть значения вида 12/31/2024.','предупреждение')
                elif order=='mixed': result.issue(filename,sheet,max(header,0)+1,'В колонке дат смешаны порядки день/месяц и месяц/день: проверьте даты вручную.','предупреждение')
            supplied_level=df['level'].notna() & df['level'].astype(str).str.strip().ne('') & ~nodata(df['level']) if 'level' in df else pd.Series(False,index=df.index)
            supplied_pressure=df['pressure'].notna() & df['pressure'].astype(str).str.strip().ne('') & ~nodata(df['pressure']) if 'pressure' in df else pd.Series(False,index=df.index)
            if detected in WELL_REQUIRED:
                for col in ('p_res','p_bh'):
                    if col in df:
                        supplied=df[col].notna()&df[col].astype(str).str.strip().ne('')&~nodata(df[col])
                        reasons.loc[supplied&numeric(df[col]).isna()]='Некорректное давление в поле '+col
            for col in ('q','p_res','p_bh','dp2','a_db','b_db','pressure','level','plan_volume')+WATER_FACTOR_NEW+('water_day',):
                if col in df:
                    hit=nodata(df[col])
                    if hit.any():
                        label=str(head[header][mapping[col]]) if col in mapping and not wide and header>=0 else col
                        result.issue(filename,sheet,max(header,0)+1,f'В колонке «{label}» {int(hit.sum())} знач. «нет данных» (−999,25 и подобные) заменены пустыми.','предупреждение')
                    df[col]=numeric(df[col],level=col=='level')
            if detected in WELL_REQUIRED:
                df=normalize_well(df,detected,reasons,numeric)
                for col in ('gas_volume_m3','water_volume_m3','water_rate'):
                    if col in mapping and col in df:df[col]*=volume_factor(head[header][mapping[col]])
                if detected=='operations':
                    kinds=df.get('kind',pd.Series(production_kind,index=df.index)).fillna(production_kind).astype(str).str.strip()
                    reasons.loc[~kinds.str.contains('отбор|withdraw|закач|inject|^$',case=False,regex=True)]='Тип эксплуатации: отбор или закачка'
                    df['kind']=kinds.apply(lambda x:'injection' if re.search('закач|inject',x,re.I) else production_kind if not x else 'withdrawal')
                    for col in ('p_res','p_bh'):
                        reasons.loc[df[col].lt(0)]='Давление не может быть отрицательным'
            if not wide and header>=0:
                done=set()
                for col in ('p_res','p_bh','pressure','p_wellhead','p_line','dp2'):
                    if col not in df or col not in mapping: continue
                    label=str(head[header][mapping[col]])
                    factor=pressure_factor(label)
                    if factor is None: continue
                    df[col]=df[col]*(factor**2 if col=='dp2' else factor); done.add(col)
                    result.issue(filename,sheet,header+1,f'Единица давления взята из заголовка «{label}»: значения пересчитаны в кгс/см² (×{factor**(2 if col=="dp2" else 1):.4g}).','предупреждение')
                if done: result.by_header.setdefault(detected,set()).update(done)
            if detected=='production':
                unit=production_unit
                label=str(head[header][mapping['q']]) if not wide else ''
                unit=rate_unit(label,unit)
                if unit!=production_unit and label: result.issue(filename,sheet,max(header,0)+1,f'Единица расхода взята из заголовка «{label}»: {unit} (выбрано: {production_unit}).','предупреждение')
                df['q']=df.q*RATE_TO_M3[unit]
                reasons.loc[~np.isfinite(df.q)|df.q.lt(0)]='Расход должен быть конечным неотрицательным числом'
                named='injection' if re.search('закач|inject',sheet,re.I) else 'withdrawal' if re.search('отбор|withdraw',sheet,re.I) else production_kind
                df['kind']=df.get('kind',pd.Series('',index=df.index)).fillna('').astype(str).apply(lambda x:'injection' if re.search('закач|inject',x,re.I) else 'withdrawal' if re.search('отбор|withdraw',x,re.I) else named)
            elif detected=='gdi':
                unit=gdi_unit
                label=str(head[header][mapping['q']])
                unit=rate_unit(label,unit)
                if unit!=gdi_unit and label: result.issue(filename,sheet,max(header,0)+1,f'Единица Q взята из заголовка «{label}»: {unit} (выбрано: {gdi_unit}).','предупреждение')
                k=RATE_TO_M3[unit]/1000      # хранится в тыс. м³/сут; коэффициенты a, b пересчитываются вместе с Q
                df['q']=df.q*k
                if k!=1:
                    if 'a_db' in df: df['a_db']=df['a_db']/k
                    if 'b_db' in df: df['b_db']=df['b_db']/k**2
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
            elif detected=='water_factor':
                # Газ хранится в млн м³, вода в м³: приставка в заголовке («тыс.», «млн», «млрд») пересчитывается.
                for col in ('gas_cum','gas_in_place'):
                    if col in mapping and col in df:
                        lab=str(head[header][mapping[col]]).lower().replace('³','3')
                        df[col]=df[col]*(1000 if 'млрд' in lab else 1 if 'млн' in lab else 0.001 if 'тыс' in lab else 1e-6 if re.search(r'м\s*3',lab) else 1)
                for col in ('water_cum','water_day'):
                    if col in mapping and col in df:
                        lab=str(head[header][mapping[col]]).lower().replace('³','3')
                        df[col]=df[col]*(10**9 if 'млрд' in lab else 10**6 if 'млн' in lab else 1000 if 'тыс' in lab else 1)
                reasons.loc[df.gas_in_place.isna()|~np.isfinite(df.gas_in_place)|df.gas_in_place.lt(0)]='Нет объёма газа в пласте (неотрицательное число, млн м³)'
                for col in ('gas_cum','wf_cum','water_cum','water_day','wf'):
                    if col not in df:df[col]=np.nan
                    reasons.loc[df[col].lt(0)&reasons.eq('')]='Отрицательное значение в колонке «'+col+'»'
            elif detected=='plan':
                # План хранится в млн м³; единицу берём из заголовка колонки («млрд», «тыс.» — пересчёт).
                label=(' '.join(str(c) for r in head[:max(0,header)] for c in r if c is not None) if wide else str(head[header][mapping['plan_volume']])).lower().replace('³','3')
                df['plan_volume']=df.plan_volume*(1000 if 'млрд' in label else 1 if 'млн' in label else 0.001 if 'тыс' in label else 1e-6 if re.search(r'м\s*3',label) else 1)
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
    if result.omitted:
        result.issues.append({'Файл':filename,'Лист':'','Строка':0,'Уровень':'предупреждение','Причина':f'Ещё {result.omitted} замечаний не показаны: в журнале первые 2000.'})
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
        old_hit=okeys.isin(nkeys); new_hit=nkeys.isin(okeys)
        if module=='gdi':
            # Исследование, загруженное без «Метода» и «Исследования», совпадает с таким же по скважине и дате:
            # иначе повторная загрузка с новыми колонками удвоит точки.
            od=pd.MultiIndex.from_frame(old[['well','date']]); nd=pd.MultiIndex.from_frame(new[['well','date']])
            blank_old=(old.method.astype(str).eq('')&old.study.astype(str).eq('')).to_numpy()
            blank_new=(new.method.astype(str).eq('')&new.study.astype(str).eq('')).to_numpy()
            old_hit=old_hit|(od.isin(nd)&(blank_old|od.isin(nd[blank_new])))
            new_hit=new_hit|(nd.isin(od)&(blank_new|nd.isin(od[blank_old])))
        base=pd.concat([old[~old_hit],new],ignore_index=True) if policy=='new' else pd.concat([old,new[~new_hit]],ignore_index=True)
    else: base=pd.concat([old,new] if policy=='new' else [new,old],ignore_index=True)
    keys={'production':['kind','well','date'],'response':['well','date','horizon'],
          'pressure_match':['object','scenario','well','date'],'groups':['well'],'object_pressure':['date'],'water_factor':['date'],'plan':['kind','group','date'],'gdi':['well','date','method','study','q','dp2'],
          'operations':['well','date','kind'],'water':['well','date'],'bottom':['well','date'],
          'construction':['well','date','element','top_m','bottom_m','diameter_mm']}[module]
    if module=='gdi': keys += [c for c in ('p_res','p_bh','a_db','b_db') if c in base]
    before=len(base); base=base.drop_duplicates(keys,keep='last').reset_index(drop=True)
    return base,before-len(base)
