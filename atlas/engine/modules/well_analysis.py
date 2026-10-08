"""Observed daily balances and transparent, conditional well diagnostics."""
import numpy as np
import pandas as pd
from atlas.engine.core.memo import cache_resource
import hashlib
from atlas.engine.core.config import ordered
from atlas.engine.core.performance import signature,select_wells
from atlas.engine.modules import production,gdi

def plain(df):
    d=df.copy(deep=False);d.attrs={};return d

def _daily(frames,settings,mapping):
    p=plain(frames.get('production',pd.DataFrame()))
    o=plain(frames.get('operations',pd.DataFrame()))
    if p.empty and o.empty:return pd.DataFrame()
    keys=['well','date','kind']
    if not p.empty:
        p=production.periods(p,settings.get('season_start',11),settings.get('season_end',4))
        p=p[keys+['q','period']].rename(columns={'q':'daily_q','period':'prod_period'})
    else:p=pd.DataFrame(columns=keys+['daily_q','prod_period'])
    if not o.empty:
        o=production.periods(o.assign(q=np.nan),settings.get('season_start',11),settings.get('season_end',4)).rename(columns={'period':'ops_period'})
        cols=keys+['ops_period']+[c for c in ('work_hours','gas_volume_m3','water_volume_m3','water_flag','p_res','p_bh','p_wellhead','p_line','temperature','comment') if c in o]
        o=o[cols]
    else:o=pd.DataFrame(columns=keys+['ops_period'])
    if o.empty and not p.empty:
        # No daily operations: the outer merge with an empty frame only costs time (it converts every date to object).
        d=p.copy();d['ops_period']=pd.Series(np.nan,index=d.index,dtype=object)
        if not d.duplicated(keys).any():d=d.sort_values(keys,kind='stable')
        else:d=p.merge(o,on=keys,how='outer',validate='one_to_one')
    else:d=p.merge(o,on=keys,how='outer',validate='one_to_one')
    for col in ('work_hours','gas_volume_m3','water_volume_m3','p_res','p_bh','p_wellhead','p_line','temperature'):
        if col not in d:d[col]=np.nan
    d['volume_source']=np.where(d.gas_volume_m3.notna(),'Суточная эксплуатация','Динамика')
    d['gas_volume_m3']=d.gas_volume_m3.combine_first(d.daily_q)
    d['period']=d.prod_period.combine_first(d.ops_period)
    d['group']=d.well.map({w:mapping.get(w,{}).get('group','Без группы') for w in d.well.unique()})
    d['active']=d.work_hours.gt(0).where(d.work_hours.notna(),d.gas_volume_m3.gt(0))
    d['q_work']=d.gas_volume_m3/d.work_hours.where(d.work_hours.gt(0))*24/1000
    dp=d.p_res**2-d.p_bh**2
    d['specific_q']=d.q_work/dp.where(dp.gt(0)&d.p_res.gt(0)&d.p_bh.ge(0))
    d['water_factor']=d.water_volume_m3/d.gas_volume_m3.where(d.gas_volume_m3.gt(0))*1e6
    if 'water_flag' not in d:d['water_flag']='Неизвестно'
    return d.sort_values(['kind','well','date']).reset_index(drop=True)

@cache_resource(max_entries=2)
def cached_dataset(token,mapping_json,_frames,_settings,_mapping):
    d=_daily(_frames,_settings,_mapping)
    if d.empty:return {'daily':d}
    totals=d.groupby(['kind','date']).gas_volume_m3.sum(min_count=1).rename('object_volume')
    groups=d.groupby(['kind','group','date']).gas_volume_m3.sum(min_count=1).rename('group_volume')
    d=d.join(totals,on=['kind','date']).join(groups,on=['kind','group','date'])
    d['share_group']=d.gas_volume_m3/d.group_volume.where(d.group_volume.gt(0))*100
    d['share_object']=d.gas_volume_m3/d.object_volume.where(d.object_volume.gt(0))*100
    d=d.join(d.groupby(['kind','period']).date.min().rename('period_start'),on=['kind','period'])
    return {'daily':d,'positions':d.groupby('well',sort=False).indices}

def dataset(frames,settings,mapping):
    tokens=[]
    for k in ('production','operations'):
        if k not in frames:continue
        df=frames[k];token=df.attrs.get('_atlas_token')
        if token is None:token=hashlib.sha256(pd.util.hash_pandas_object(df,index=True).values.tobytes()+str(list(df.columns)).encode()).hexdigest()
        tokens.append((k,token))
    return cached_dataset(signature([tokens,settings.get('season_start',11),settings.get('season_end',4)]),signature(mapping),frames,settings,mapping)

SEASON_LABELS={'period':'Период','gas_volume':'Объем газа, млн м³','mean_active':'Средний суточный объем активных дней, тыс. м³',
 'active_days':'Отработанные дни','hours':'Известные часы работы','hours_days':'Дней с учетом часов',
 'q_work':'Средний расход в часы работы, тыс. м³/сут','gas_days':'Дней с данными газа','object_days':'Дней с данными объекта',
 'coverage':'Покрытие дней объекта, %','calendar_span':'Календарный интервал данных, дней',
 'water_volume':'Измеренный объем воды, м³','group_share':'Доля в объеме группы, %','object_share':'Доля в объеме объекта, %'}

def seasons(d,all_data):
    rows=[]
    for period,g in d.groupby('period',sort=False):
        base=all_data[all_data.kind.eq(g.kind.iloc[0])&all_data.period.eq(period)]
        dates=base.loc[base.gas_volume_m3.notna(),'date'].drop_duplicates()
        hours=g.work_hours.notna();both=g.work_hours.gt(0)&g.gas_volume_m3.notna()
        active=g.active&g.gas_volume_m3.notna();volume=g.gas_volume_m3.sum(min_count=1)
        group=base.loc[base.group.eq(g.group.iloc[0]),'gas_volume_m3'].sum(min_count=1)
        obj=base.gas_volume_m3.sum(min_count=1)
        rows.append({'period':period,'gas_volume':volume/1e6,'mean_active':g.loc[active,'gas_volume_m3'].mean()/1000,
            'active_days':int(g.active.sum()),'hours':g.work_hours.sum(min_count=1),'hours_days':int(hours.sum()),
            'q_work':g.loc[both,'gas_volume_m3'].sum()/g.loc[both,'work_hours'].sum()*24/1000 if both.any() else np.nan,
            'gas_days':int(g.gas_volume_m3.notna().sum()),'object_days':len(dates),
            'coverage':g.gas_volume_m3.notna().sum()/len(dates)*100 if len(dates) else np.nan,
            'calendar_span':(dates.max()-dates.min()).days+1 if len(dates) else 0,
            'water_volume':g.water_volume_m3.sum(min_count=1),'group_share':volume/group*100 if group>0 else np.nan,
            'object_share':volume/obj*100 if obj>0 else np.nan,'_end':g.date.max()})
    return pd.DataFrame(rows).sort_values('_end').drop(columns='_end') if rows else pd.DataFrame(columns=SEASON_LABELS)

def gdi_history(df,threshold=.95,delta=None):
    if df.empty:return pd.DataFrame()
    history=gdi.analyze(df,threshold)
    valid_points=df[df.q.gt(0)&df.dp2.gt(0)&np.isfinite(df.q)&np.isfinite(df.dp2)]
    ranges=valid_points.groupby(gdi.KEYS).dp2.agg(['min','max'])
    distinct=valid_points.groupby(gdi.KEYS).q.nunique()
    history=history.join(ranges,on=gdi.KEYS).join(distinct.rename('distinct_q'),on=gdi.KEYS)
    history['reliable']=history.r2.ge(threshold)&history.distinct_q.ge(3)&history.a.ge(0)&history.b.ge(0)&(history.a+history.b).gt(0)
    history['reference_dp2']=np.nan;history['q_reference']=np.nan
    for method,part in history.groupby('method',dropna=False):
        valid=part[part.reliable]
        if valid.empty:continue
        lo,hi=valid['min'].max(),valid['max'].min()
        ref=float(delta) if delta is not None else (lo+hi)/2 if hi>lo else np.nan
        history.loc[part.index,'reference_dp2']=ref
        for i,r in valid.iterrows():
            if not np.isfinite(ref) or not r['min']<=ref<=r['max']:continue
            history.loc[i,'q_reference']=2*ref/(r.a+np.sqrt(r.a*r.a+4*r.b*ref)) if r.b>0 else ref/r.a
    return history.sort_values(['date','method','study']).reset_index(drop=True)

def latest_snapshot(df,well,asof):
    if df.empty:return df
    d=select_wells(df,[well]);d=d[d.date.le(pd.Timestamp(asof))]
    return d[d.date.eq(d.date.max())].copy() if not d.empty else d

def water_observations(frames,well,asof):
    parts=[]
    for module in ('operations','water'):
        if module not in frames:continue
        d=select_wells(frames[module],[well]);d=d[d.date.le(pd.Timestamp(asof))]
        if module=='operations' and 'kind' in d:d=d[d.kind.eq('withdrawal')]
        for _,r in d.iterrows():
            amount=r.get('water_volume_m3',np.nan) if module=='operations' else r.get('water_rate',np.nan)
            flag=r.get('water_flag','Неизвестно')
            state='Вода измерена' if pd.notna(amount) and amount>0 else 'Вода отмечена' if flag=='Да' else 'Вода не отмечена' if flag=='Нет' else 'Измеренный расход воды равен нулю' if pd.notna(amount) and amount==0 else 'Нет сведений'
            if state=='Нет сведений':continue
            parts.append({'Дата':r.date,'Источник':module,'Состояние':state,'Признак':flag,'Величина':amount,
                          'Единица':'м³ за сутки' if module=='operations' else 'м³/сут','Противоречие':flag=='Нет' and pd.notna(amount) and amount>0})
    return pd.DataFrame(parts).sort_values('Дата') if parts else pd.DataFrame(columns=['Дата','Источник','Состояние','Признак','Величина','Единица','Противоречие'])

def signals(d,stats,history,water,bottom,construction,threshold=10):
    out=[]
    def add(topic,fact,interpretation,next_step='Проверить исходные измерения и режим работы.'):
        out.append({'Раздел':topic,'Факт':fact,'Вывод':interpretation,'Что проверить':next_step})
    if d.empty:add('Эксплуатация','Нет суточных данных выбранной скважины.','Динамика эксплуатации не рассчитывается.','Загрузить динамику или суточную эксплуатацию.')
    else:
        if not d.work_hours.notna().any():add('Часы работы','Учет часов не загружен.','Отработанные часы и расход в часы работы неизвестны.','Загрузить шаблон суточной эксплуатации.')
        contradictions=d.work_hours.eq(0)&d.gas_volume_m3.gt(0)
        if contradictions.any():add('Качество',f'{int(contradictions.sum())} суток: объем газа > 0 при нуле часов.','Суточный баланс и учет часов противоречат друг другу.')
        for period,g in d.groupby('period',sort=False):
            g=g.sort_values('date');active=g[g.active&g.gas_volume_m3.gt(0)]
            if active.empty or (active.date.max()-active.date.min()).days<28:continue
            first=active[active.date.lt(active.date.min()+pd.Timedelta(days=14))]
            last=active[active.date.gt(active.date.max()-pd.Timedelta(days=14))]
            if min(len(first),len(last))<7:continue
            change=(last.gas_volume_m3.median()/first.gas_volume_m3.median()-1)*100
            shares=first.share_group.median(),last.share_group.median()
            relative=(shares[1]/shares[0]-1)*100 if shares[0]>0 else np.nan
            hours=first.work_hours.median(),last.work_hours.median()
            stable_hours=all(pd.notna(v) for v in hours) and hours[0]>0 and abs(hours[1]/hours[0]-1)<=.15
            if change<=-threshold:
                fact=f'{period}: медианный суточный объем последних 14 дней ниже первых на {abs(change):.1f}%; выборки {len(first)} и {len(last)} активных дней.'
                if np.isfinite(relative):fact+=f' Изменение доли в группе: {relative:+.1f}%.'
                inference='Косвенный сигнал относительного ухудшения отдачи скважины.' if relative<=-threshold and stable_hours else 'Снижение наблюдаемого объема. Изменение продуктивности пока не подтверждено.'
                if not stable_hours:inference+=' Часы работы отсутствуют или изменились более чем на 15%.'
                add('Эксплуатация',fact,inference,'Сопоставить часы, давления, ограничения шлейфа, воду и последние ГДИ.')
        low=stats[stats.coverage.lt(80)] if not stats.empty else stats
        for _,r in low.iterrows():add('Покрытие',f'{r.period}: данные газа есть за {r.gas_days:.0f} из {r.object_days:.0f} наблюдаемых дней объекта ({r.coverage:.1f}%).','Сезонные итоги неполные; пропуски не считаются простоем.','Проверить пропуски, исключенные точки и полноту импорта.')
    if history.empty:add('ГДИ','Нет исследований в выбранном периоде.','Сравнение продуктивности по ГДИ недоступно.','Загрузить точки ГДИ.')
    else:
        for method,h in history.groupby('method',dropna=False):
            comparable=h[h.reliable&h.q_reference.notna()].sort_values('date')
            if len(comparable)<2 or comparable.date.nunique()<2:
                add('ГДИ',f'{method or "Метод не указан"}: нет двух надежных исследований с общим диапазоном ΔP².','Автоматическое заключение об изменении продуктивности не сформировано.','Нужны минимум три разных Q, достаточное R² и общий измеренный диапазон депрессий.');continue
            latest=comparable.iloc[-1];previous=comparable[comparable.date.lt(latest.date)].iloc[-1]
            change=(latest.q_reference/previous.q_reference-1)*100
            state='Снижение расчетной отдачи при одинаковом ΔP².' if change<=-threshold else 'Повышение расчетной отдачи при одинаковом ΔP².' if change>=threshold else 'Изменение меньше заданного порога.'
            add('ГДИ',f'{method or "Метод не указан"}: {previous.date:%d.%m.%Y} → {latest.date:%d.%m.%Y}, Q при ΔP²={latest.reference_dp2:.3g}: {previous.q_reference:.2f} → {latest.q_reference:.2f} тыс. м³/сут ({change:+.1f}%).',state,'Сопоставить условия исследований, давления и состояние скважины. Модель ΔP²=aQ+bQ² имеет ограничения применимости.')
    if water.empty:add('Вода','Наблюдения воды не загружены.','Наличие обводненности неизвестно; уровень жидкости сам по себе ее не подтверждает.','Загрузить контроль воды или суточный объем воды.')
    else:
        r=water.iloc[-1];add('Вода',f'Последнее наблюдение {r["Дата"]:%d.%m.%Y}: {r["Состояние"]}.','Состояние относится к дате наблюдения.','Сопоставить появление воды с расходом, давлением и забоем.')
        if water['Противоречие'].any():add('Качество','Положительная измеренная вода вместе с признаком «Нет».','В журнале воды есть противоречивые записи.')
    if bottom.empty:add('Забой','Замеры забоя не загружены.','Текущий забой неизвестен.','Загрузить шаблон замеров забоя.')
    elif len(bottom)>=2:
        b=bottom.sort_values('date');change=b.iloc[-1].bottom_m-b.iloc[-2].bottom_m
        if change<0:add('Забой',f'Последний отбитый забой на {abs(change):.1f} м выше предыдущего.','Возможны заполнение забоя или различие условий замера.','Сверить метод, диаметр шаблона и результаты очистки.')
    if construction.empty:add('Конструкция','Конструкция не загружена на выбранную дату.','Схема и положение интервалов недоступны.','Загрузить полный снимок конструкции с датой.')
    elif not bottom.empty:
        depth=bottom.sort_values('date').iloc[-1].bottom_m
        perf=construction[construction.element.str.contains('перфор|фильтр',case=False,regex=True)]
        for _,r in perf[perf.bottom_m.gt(depth)].iterrows():
            add('Забой',f'Часть интервала {r.top_m:g}–{r.bottom_m:g} м расположена ниже отбитого забоя {depth:g} м.','Есть геометрическое несоответствие замера и интервала конструкции.','Проверить привязку глубин и актуальность снимка конструкции.')
    return pd.DataFrame(out)

def metrics(a):
    """Карточки поскважинного анализа: (подпись, значение, знаков после запятой или None для текста, подсказка)."""
    stats=a['seasons'];data=a['daily']
    water=a['water'];last=water.iloc[-1] if not water.empty else None
    state='Неизвестно' if last is None else 'Есть' if last['Состояние'] in ('Вода измерена','Вода отмечена') else 'Не отмечена' if last['Признак']=='Нет' else 'Замер равен нулю'
    return [('Газ за выбранные периоды, млн м³',stats.gas_volume.sum(min_count=1) if not stats.empty else np.nan,3,None),
            ('Средний суточный объем, тыс. м³',data.loc[data.active,'gas_volume_m3'].mean()/1000 if not data.empty else np.nan,2,None),
            ('Отработанные дни',stats.active_days.sum() if not stats.empty else np.nan,0,None),
            ('Известные часы работы',stats.hours.sum(min_count=1) if not stats.empty else np.nan,1,None),
            ('Последний отбитый забой, м',a['bottom'].iloc[-1].bottom_m if not a['bottom'].empty else np.nan,1,None),
            ('Вода по последнему контролю',state,None,'Нет наблюдений' if last is None else last['Дата'].strftime('%d.%m.%Y')+'; состояние относится к дате наблюдения.')]

def _analyze(frames,settings,mapping,well,kind='withdrawal',periods=None,delta=None,threshold=10,method=None,asof=None):
    context=dataset(frames,settings,mapping);all_data=context['daily']
    cutoff=pd.Timestamp(asof) if asof is not None else None
    if cutoff is not None and not all_data.empty:all_data=all_data[all_data.date.le(cutoff)]
    original=context['daily']
    d=original.iloc[context.get('positions',{}).get(well,[])].copy() if not original.empty else pd.DataFrame()
    if cutoff is not None and not d.empty:d=d[d.date.le(cutoff)]
    if not d.empty:
        d=d[d.kind.eq(kind)]
        if periods is not None:d=d[d.period.isin(periods)]
        if not d.empty:
            # Preserve object/group observations on days when this well has no record.
            base=all_data[all_data.kind.eq(kind)&all_data.period.isin(d.period.unique())]
            group=mapping.get(well,{}).get('group','Без группы')
            ref=base[['date','period','period_start','object_volume']].drop_duplicates('date')
            gv=base[base.group.eq(group)].groupby('date').gas_volume_m3.sum(min_count=1).rename('group_volume')
            ref=ref.join(gv,on='date').sort_values('date')
            ref['object_cumulative']=ref.groupby('period',sort=False).object_volume.cumsum()/1e6
            ref['group_cumulative']=ref.groupby('period',sort=False).group_volume.cumsum()/1e6
            d=ref.merge(d.drop(columns=['period','period_start','object_volume','group_volume','share_group','share_object']),on='date',how='outer')
            d['well']=well;d['group']=group;d['kind']=kind;d['active']=d.active.fillna(False)
            d['share_group']=d.gas_volume_m3/d.group_volume.where(d.group_volume.gt(0))*100
            d['share_object']=d.gas_volume_m3/d.object_volume.where(d.object_volume.gt(0))*100
        d=d.sort_values('date')
    stats=seasons(d,all_data) if not d.empty else pd.DataFrame(columns=SEASON_LABELS)
    asof=cutoff if cutoff is not None else d.date.max() if not d.empty else pd.Timestamp.max.normalize()
    gd=select_wells(frames['gdi'],[well]) if 'gdi' in frames else pd.DataFrame()
    if not gd.empty:gd=gd[gd.date.le(asof)]
    if method is not None and not gd.empty:gd=gd[gd.method.eq(method)]
    if periods is not None and not gd.empty:
        # Season selections describe object date intervals; do not drop studies with an empty Season field.
        intervals=all_data[all_data.kind.eq(kind)&all_data.period.isin(periods)].groupby('period').date.agg(['min','max']) if not all_data.empty else pd.DataFrame()
        mask=pd.Series(False,index=gd.index)
        for _,span in intervals.iterrows():mask|=gd.date.between(span['min'],span['max'])
        if not intervals.empty:gd=gd[mask]
    history=gdi_history(gd,settings.get('r2_threshold',.95),delta)
    bottom=select_wells(frames['bottom'],[well]) if 'bottom' in frames else pd.DataFrame()
    if not bottom.empty:bottom=bottom[bottom.date.le(asof)].sort_values('date')
    construction=latest_snapshot(frames.get('construction',pd.DataFrame()),well,asof)
    water=water_observations(frames,well,asof)
    return {'well':well,'kind':kind,'daily':d,'seasons':stats,'gdi':gd,'gdi_history':history,'bottom':bottom,
            'construction':construction,'water':water,'signals':signals(d,stats,history,water,bottom,construction,threshold),
            'asof':asof,'periods':[] if d.empty else ordered(d.period)}


@cache_resource(max_entries=12)
def cached_analysis(token,parameters,_frames,_settings,_mapping):
    value=_analyze(_frames,_settings,_mapping,**parameters);value['_cache_token']=token+':'+signature(parameters);return value


def analyze(frames,settings,mapping,well,kind='withdrawal',periods=None,delta=None,threshold=10,method=None,asof=None):
    tokens=[]
    for name in ('production','operations','gdi','water','bottom','construction'):
        if name not in frames:continue
        frame=frames[name];token=frame.attrs.get('_atlas_token')
        if token is None:token=hashlib.sha256(pd.util.hash_pandas_object(frame,index=True).values.tobytes()+str(list(frame.columns)).encode()).hexdigest()
        tokens.append((name,token))
    parameters=dict(well=well,kind=kind,periods=periods,delta=delta,threshold=threshold,method=method,asof=asof)
    return cached_analysis((tokens[0][1]+':' if tokens else '')+signature([tokens,mapping,settings.get('r2_threshold',.95),settings.get('season_start',11),settings.get('season_end',4)]),parameters,frames,settings,mapping)
