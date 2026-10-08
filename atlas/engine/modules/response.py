import pandas as pd
from atlas.engine.core.config import COLORS, ordered

def horizon_colors(horizons,working):
    controls=[h for h in ordered(horizons) if h not in working]
    colors={h:COLORS[0] for h in horizons if h in working}
    colors.update({h:COLORS[1+i%(len(COLORS)-1)] for i,h in enumerate(controls)})
    return colors

def statistics(df):
    if df.empty: return pd.DataFrame()
    return df.groupby('horizon',sort=True).agg(Скважин=('well','nunique'),Замеров=('level','count'),
        Начало=('date','min'),Окончание=('date','max'),Минимум_м=('level','min'),Максимум_м=('level','max')).reset_index().rename(columns={'horizon':'Горизонт'})
