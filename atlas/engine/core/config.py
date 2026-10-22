from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[3]
STORAGE = Path(os.environ.get('GAS_ATLAS_STORAGE', ROOT / 'storage')).resolve()
VERSION = '5.8.0-py3820'
MODULES = {'production': 'Производительность скважин', 'histograms':'Гистограммы по эксплуатации скважин', 'gdi': 'ГДИ', 'response': 'Графики реагирования', 'object_pressure':'Давление объекта',
           'operations':'Суточная эксплуатация', 'water':'Контроль воды', 'bottom':'Замеры забоя',
           'construction':'Конструкция', 'well_dashboard':'Поскважинный анализ', 'pressure_match':'Кроссплот давлений', 'plan':'План по группам', 'water_factor':'Вынос воды по объекту', 'ggh':'ГГХ', 'elpro':'ЭЛПРО', 'gas_db':'БД по учету газа', 'well_geo':'Положение и перфорация скважин', 'annulus':'Межколонные давления', 'gis_packs':'ГИС: пачки', 'gis_observations':'ГИС: замеры', 'gis_intervals':'ГИС: интервалы'}
COLORS = ['#dc3545', '#2563eb', '#169b62', '#ed8b23', '#9955cc', '#149ba5', '#bd548d', '#8c7542']
DEFAULT_SETTINGS = {'season_start': 11, 'season_end': 4, 'r2_threshold': 0.95,
                    'working_horizons': [], 'pressure_unit': 'кгс/см²', 'panels': {},
                    'manometer_wells':[], 'object_pressure_horizons':[],
                    'chart_style':{'grid':True,'legend':True,'autoscale':True}}

def natural_key(value):
    import re
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', str(value))]

def ordered(values):
    return sorted(set(str(v) for v in values), key=natural_key)


def parse_wells(text):
    import re
    return ordered(w.lstrip('№#') for w in re.split(r'[,;\s]+', text.strip()) if w.lstrip('№#'))


def histogram_size(value, count):
    if value == 'Все':
        return max(1, count)
    if value == 'Авто':
        return 10
    return max(1, int(value))

# Условные «нет данных» из LAS и выгрузок приборов: число, а не пустая ячейка, поэтому читаются как пропуск.
NODATA=(-999.25,-999.0,-9999.0,-99999.0)


class DataRangeError(ValueError):
    """Даты в данных не укладываются в допустимый период; текст (какая группа, какие даты) показывается как есть."""


MAX_SPAN_DAYS = 3660
# Нулевая дата из БД читается как 01.01.1970 или 30.12.1899: только эти точные значения считаются «нет даты».
# Любая другая ранняя дата (история объекта с прошлых лет) допустима.
NULL_DATES = ('1970-01-01', '1899-12-30', '1899-12-31', '1900-01-01')


def implausible_dates(frame):
    """Маска строк с точной «нулевой» датой (пустая дата из БД)."""
    import pandas as pd
    return frame.date.dt.normalize().isin(pd.to_datetime(list(NULL_DATES)))


def bounded_dates(frame, label):
    """Строки периода без дат из будущего (шаблоны на ещё не наступившие дни) и без «нулевых» дат (01.01.1970 и т. п.).
    Если и после этого период длиннее 10 лет, это опечатка в дате: ошибка с перечнем подозрительных лет."""
    import pandas as pd
    bad = frame.date.gt(pd.Timestamp.today().normalize()) | implausible_dates(frame)
    if bad.any():
        frame = frame[~bad]
    if frame.empty:
        return frame
    lo, hi = frame.date.min(), frame.date.max()
    if (hi - lo).days > MAX_SPAN_DAYS:
        years = frame.date.dt.year.value_counts().sort_index()
        rare = [f'{y} ({n} стр.)' for y, n in years.items() if n <= max(1, len(frame) // 200)][:6]
        hint = ' Подозрительные годы: ' + ', '.join(rare) + '.' if rare else ''
        raise DataRangeError(
            f'{label}: даты с {lo:%d.%m.%Y} по {hi:%d.%m.%Y}, это больше 10 лет.{hint} '
            'Проверьте опечатки в датах (в «Проверке данных» или в разделе «Исключённые точки») и поле «Сезон».')
    return frame
