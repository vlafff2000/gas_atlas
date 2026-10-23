"""Конструктор графиков: инженер сам собирает график из рядов (как в Excel).

Ряд — поле Y и поле X из любых наборов проекта, скважины (или группы), период, ось Y1–Y5, вид (линия, точки).
X — любое поле: дата или число. Если X и Y из разных наборов, строки сопоставляются по ключу ряда:
«скважина + дата» (по умолчанию), «дата», «скважина», «ближайшая дата ±N дней»; на ключ с несколькими значениями X
берётся их среднее. Расчётов здесь нет: только выбор данных и представление (``Chart`` из контракта).

Данные: давления в проекте абсолютные и не пересчитываются; «нет данных» (−999,25 и подобные) — пропуск;
нули (сутки простоя) остаются точками. Подписи осей и заголовок — из названий полей и единиц, но любое из них
инженер задаёт вручную (``layout.title``, ``layout.x_label``, ``layout.axes``).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping

import numpy as np
import pandas as pd

from atlas.engine.core.config import NODATA, natural_key
from atlas.engine.core.import_rules import FIELDS as IMPORT_FIELDS
from atlas.engine.core.loader import group_key

from ..chart_style import bound, clean_axes, clean_chart, clean_look
from ..contract import Axis, Chart, Data, Module, ModuleSpec, Note, Param, ParamError, Result, Series, Stat
from . import builder_calc as calc
from ._production import NEUTRAL_PREFIXES
from ..domain import DatasetKind
from .. import model_source

K = DatasetKind
P_UNIT, Q_UNIT, WF_UNIT = 'кгс/см²', 'тыс. м³/сут', 'л/тыс. м³'

# Категории дерева полей по порядку.
CATEGORIES = (
    ('prod', 'Производительность скважин'),
    ('pressure', 'Давления'),
    ('water', 'Вода'),
    ('object', 'Данные по объекту'),
    ('gdi', 'ГДИ'),
    ('response', 'Реагирование горизонтов'),
    ('annulus', 'Межколонные'),
    ('ggh', 'ГГХ'),
    ('gis', 'ГИС и ГВК'),
    ('model', 'Модель ГДМ'),
    ('construction', 'Конструкция и забой'),
    ('other', 'Прочее'),
)
# Категория по умолчанию для колонок набора, которых нет в FIELDS.
DATASET_CATEGORY = {
    K.PRODUCTION: 'prod', K.ELPRO: 'prod', K.OPERATIONS: 'prod', K.GDI: 'gdi', K.RESPONSE: 'response',
    K.OBJECT_PRESSURE: 'pressure', K.PRESSURE_MATCH: 'pressure', K.WATER: 'water', K.WATER_FACTOR: 'water',
    K.GAS_DB: 'object', K.PLAN: 'object', K.ANNULUS: 'annulus', K.GGH: 'ggh', K.CONSTRUCTION: 'construction',
    K.BOTTOM: 'construction', K.GIS_PACKS: 'gis', K.GIS_OBSERVATIONS: 'gis', K.GIS_INTERVALS: 'gis', K.MODEL: 'model',
}


@dataclass(frozen=True)
class FieldMeta:
    category: str
    label: str
    unit: str = ''
    scale: float = 1.0          # множитель на экран: суточный отбор хранится в м³/сут, показывается в тыс. м³/сут


# (набор, колонка) → подпись, единица, категория. Остальные числовые колонки — с именем колонки, категория набора.
FIELDS: dict[tuple[DatasetKind, str], FieldMeta] = {
    (K.PRODUCTION, 'q'): FieldMeta('prod', 'Суточный расход газа', Q_UNIT, 1 / 1000),
    (K.ELPRO, 'q'): FieldMeta('prod', 'Q газа (ЭЛПРО)', Q_UNIT),
    (K.ELPRO, 'p'): FieldMeta('pressure', 'P газа (ЭЛПРО)', P_UNIT),
    (K.ELPRO, 't'): FieldMeta('prod', 'T газа (ЭЛПРО)', '°C'),
    (K.ELPRO, 'y'): FieldMeta('prod', 'Открытие КРУ (ЭЛПРО)', '%'),
    (K.ELPRO, 'hours'): FieldMeta('prod', 'В работе (ЭЛПРО)', 'ч'),
    (K.OPERATIONS, 'work_hours'): FieldMeta('prod', 'Часы работы', 'ч'),
    (K.OPERATIONS, 'gas_volume_m3'): FieldMeta('prod', 'Объём газа за сутки', 'м³'),
    (K.OPERATIONS, 'temperature'): FieldMeta('prod', 'Температура', '°C'),
    (K.OPERATIONS, 'water_volume_m3'): FieldMeta('water', 'Объём воды за сутки', 'м³'),
    (K.OPERATIONS, 'p_res'): FieldMeta('pressure', 'Рпл (эксплуатация)', P_UNIT),
    (K.OPERATIONS, 'p_bh'): FieldMeta('pressure', 'Рзаб (эксплуатация)', P_UNIT),
    (K.OPERATIONS, 'p_wellhead'): FieldMeta('pressure', 'Руст', P_UNIT),
    (K.OPERATIONS, 'p_line'): FieldMeta('pressure', 'Р в шлейфе', P_UNIT),
    (K.OBJECT_PRESSURE, 'pressure'): FieldMeta('pressure', 'Давление объекта', P_UNIT),
    (K.OBJECT_PRESSURE, 'p_res'): FieldMeta('pressure', 'Рпл объекта', P_UNIT),
    (K.PRESSURE_MATCH, 'fact'): FieldMeta('pressure', 'Давление: факт', P_UNIT),
    (K.PRESSURE_MATCH, 'model'): FieldMeta('pressure', 'Давление: модель', P_UNIT),
    (K.GDI, 'q'): FieldMeta('gdi', 'Q (ГДИ)', Q_UNIT),
    (K.GDI, 'p_res'): FieldMeta('gdi', 'Рпл (ГДИ)', P_UNIT),
    (K.GDI, 'p_bh'): FieldMeta('gdi', 'Рзаб (ГДИ)', P_UNIT),
    (K.GDI, 'dp2'): FieldMeta('gdi', 'ΔP²', 'кгс²/см⁴'),
    (K.GDI, 'a_db'): FieldMeta('gdi', 'Коэффициент a (база)'),
    (K.GDI, 'b_db'): FieldMeta('gdi', 'Коэффициент b (база)'),
    (K.RESPONSE, 'level'): FieldMeta('response', 'Уровень жидкости', 'м'),
    (K.RESPONSE, 'pressure'): FieldMeta('response', 'Рпл приведённое', P_UNIT),
    (K.WATER, 'water_rate'): FieldMeta('water', 'Расход воды', 'м³/сут'),
    (K.WATER, 'salinity_g_l'): FieldMeta('water', 'Минерализация', 'г/л'),
    (K.WATER_FACTOR, 'gas_cum'): FieldMeta('water', 'Накопленный расход газа', 'млн м³'),
    (K.WATER_FACTOR, 'wf_cum'): FieldMeta('water', 'Водный фактор нарастающий', WF_UNIT),
    (K.WATER_FACTOR, 'water_cum'): FieldMeta('water', 'Накопленная вода', 'м³'),
    (K.WATER_FACTOR, 'water_day'): FieldMeta('water', 'Расход воды по объекту', 'м³/сут'),
    (K.WATER_FACTOR, 'wf'): FieldMeta('water', 'Водный фактор', WF_UNIT),
    (K.WATER_FACTOR, 'gas_in_place'): FieldMeta('object', 'Объём газа в пласте', 'млн м³'),
    (K.GAS_DB, 'gas'): FieldMeta('object', 'Суточный объём газа по объекту', Q_UNIT),
    (K.GAS_DB, 'water'): FieldMeta('water', 'Вынос воды по объекту', 'м³'),
    (K.PLAN, 'plan_volume'): FieldMeta('object', 'План по группе', 'млн м³'),
    (K.ANNULUS, 'q'): FieldMeta('annulus', 'Расход из МКП'),
    (K.ANNULUS, 'p'): FieldMeta('annulus', 'Межколонное давление', P_UNIT),
    (K.GGH, 'level'): FieldMeta('ggh', 'Уровень (ГГХ)', 'м'),
    (K.GGH, 'depth'): FieldMeta('ggh', 'Глубина отбора проб', 'м'),
    (K.GGH, 'gas'): FieldMeta('ggh', 'Газонасыщенность', 'см³/л'),
    (K.GIS_PACKS, 'gvk_abs_m'): FieldMeta('gis', 'ГВК а.о.', 'м'),
    (K.GIS_PACKS, 'h_eff_m'): FieldMeta('gis', 'hг эф', 'м'),
    (K.GIS_PACKS, 'kg_avg'): FieldMeta('gis', 'Кг ср.взв', 'д.ед.'),
    (K.GIS_PACKS, 'floor_m'): FieldMeta('gis', 'Этаж', 'м'),
    (K.CONSTRUCTION, 'top_m'): FieldMeta('construction', 'Верх интервала', 'м'),
    (K.CONSTRUCTION, 'bottom_m'): FieldMeta('construction', 'Низ интервала', 'м'),
    (K.CONSTRUCTION, 'diameter_mm'): FieldMeta('construction', 'Наружный диаметр', 'мм'),
    (K.CONSTRUCTION, 'inner_diameter_mm'): FieldMeta('construction', 'Внутренний диаметр', 'мм'),
    (K.BOTTOM, 'bottom_m'): FieldMeta('construction', 'Текущий забой', 'м'),
    (K.BOTTOM, 'tool_diameter_mm'): FieldMeta('construction', 'Диаметр шаблона', 'мм'),
}
SKIP = {'np', '_row'}             # служебные числовые колонки: номер строки файла, № п/п ЭЛПРО
KINDS = {'withdrawal': 'Отбор', 'injection': 'Закачка'}
KEYS = {'well_date': 'скважина + дата', 'date': 'дата', 'well': 'скважина', 'nearest': 'ближайшая дата'}
SOURCES = {'field': 'поле данных', 'formula': 'формула'}
AXES = ('y', 'y2', 'y3', 'y4', 'y5')
VIEWS = {'line': 'линия', 'points': 'точки', 'line_points': 'линия с точками', 'bar': 'столбцы', 'area': 'область', 'step': 'ступенчатая'}
STACKABLE = ('bar', 'area')       # стопка («Стопка» в ряду) — у столбцов и областей; у остальных видов поле не действует
MAX_DAYS = 366
MANY_SERIES = 200
SPARSE = 60                       # столько точек и меньше — линия с маркерами
GAP_DAYS, GAP_STEPS = 7, 5        # линия по датам рвётся, если записей нет дольше 7 суток и 5 обычных шагов
DEFAULT_LAYOUT: dict[str, Any] = {'series': [], 'title': '', 'x_label': '', 'axes': {}}


def _entity(frame: pd.DataFrame) -> str:
    """По чему ряд делится на кривые: скважина, иначе группа (план), иначе одна кривая по объекту."""
    return 'well' if 'well' in frame else 'group' if 'group' in frame and 'well' not in frame else ''


def _value_kind(series: pd.Series) -> str | None:
    if pd.api.types.is_datetime64_any_dtype(series):
        return 'date'
    if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
        return 'number'
    return None


def _numbers(series: pd.Series) -> pd.Series:
    """Число; «нет данных» (−999,25 и подобные) — пропуск, ноль остаётся нулём."""
    values = pd.to_numeric(series, errors='coerce').astype(float)
    return values.mask(values.isin(NODATA))


def meta(kind: DatasetKind, column: str) -> FieldMeta:
    if kind is K.MODEL and column not in ('date', 'model'):
        label, unit = model_source.column_meta(column)
        return FieldMeta('model', label, unit)
    if column == 'date':
        return FieldMeta(DATASET_CATEGORY.get(kind, 'other'), 'Дата')
    return FIELDS.get((kind, column)) or FieldMeta(DATASET_CATEGORY.get(kind, 'other'), IMPORT_FIELDS.get(column, column))


def fields_of(kind: DatasetKind, frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Числовые и датовые поля набора, в которых есть хотя бы одно значение."""
    out = []
    for column in frame.columns:
        if column.startswith('_') or column in SKIP:
            continue
        vk = _value_kind(frame[column])
        if vk is None:
            continue
        present = frame[column].notna() if vk == 'date' else _numbers(frame[column]).notna()
        if not present.any():
            continue
        m = meta(kind, column)
        out.append({'id': f'{kind.value}.{column}', 'dataset': kind.value, 'dataset_label': kind.label,
                    'field': column, 'label': m.label, 'unit': m.unit, 'kind': vk, 'category': m.category})
    return out


def catalog(data: Data) -> dict[str, Any]:
    """Дерево полей по категориям и сведения о наборах (скважины или группы, режимы, даты) для карточек рядов."""
    by_category: dict[str, list[dict[str, Any]]] = {c: [] for c, _ in CATEGORIES}
    datasets = []
    for kind in DatasetKind:
        frame = data[kind] if kind in data else None
        if frame is None or frame.empty:
            continue
        fields = fields_of(kind, frame)
        if not fields:
            continue
        for f in fields:
            if f['field'] != 'date':          # дата — общее поле X, в дереве не повторяется по каждому набору
                by_category[f['category']].append(f)
        entity = _entity(frame)
        entities = sorted({str(v) for v in frame[entity].dropna() if str(v) != ''}, key=natural_key) if entity else []
        kinds = [{'value': v, 'label': KINDS.get(v, v)} for v in sorted(frame['kind'].dropna().astype(str).unique())] \
            if 'kind' in frame else []
        dates = pd.to_datetime(frame['date'], errors='coerce').dropna() if 'date' in frame else pd.Series(dtype='datetime64[ns]')
        datasets.append({'id': kind.value, 'label': kind.label, 'entity': entity, 'entities': entities, 'kinds': kinds,
                         'fields': fields,
                         'date_min': dates.min().strftime('%Y-%m-%d') if len(dates) else None,
                         'date_max': dates.max().strftime('%Y-%m-%d') if len(dates) else None})
    categories = [{'id': c, 'label': label, 'fields': sorted(by_category[c], key=lambda f: (f['label'], f['dataset_label']))}
                  for c, label in CATEGORIES if by_category[c]]
    wells = sorted({w for d in datasets if d['entity'] == 'well' for w in d['entities']}, key=natural_key)
    return {'categories': categories, 'datasets': datasets, 'wells': wells,
            'keys': [{'value': k, 'label': v} for k, v in KEYS.items()], 'model_notes': list(getattr(data, 'model_notes', []))}


# ---------- макет ----------

@dataclass
class Row:
    index: int                  # номер ряда с 1, как на экране
    dataset: DatasetKind
    y: str
    x_dataset: DatasetKind
    x: str
    wells: list[str]
    date_from: str
    date_to: str
    kind: str                   # режим (отбор / закачка); пусто — все
    axis: str
    view: str
    stack: str
    key: str
    days: int
    name: str
    hidden: bool
    look: dict[str, Any] = field(default_factory=dict)     # ручной вид ряда (atlas/chart_style.py)
    source: str = 'field'       # 'field' — поле данных, 'formula' — формула по другим рядам (этап 4)
    formula: calc.Formula | None = None
    transform: calc.Transform = field(default_factory=calc.Transform)
    unit: str = ''              # ручная единица; пусто — по полю и преобразованию
    well_mode: str = 'fixed'    # 'fixed' — скважины ряда (wells), 'current' — скважина макета (layout.current_well)
    x_transform: calc.Transform = field(default_factory=calc.Transform)    # преобразование X (накопленное и т. п.)
    x_scope: str = 'curve'      # откуда X: 'curve' — как в наборе, 'group' — сумма по группе скважины, 'object' — по всем скважинам


X_SCOPES = {'curve': 'как в наборе (по каждой скважине)', 'group': 'сумма по группе скважины', 'object': 'сумма по объекту'}
X_OPS = ('none', 'cumsum', 'mul', 'div', 'add', 'diff')


def _kind(value: Any, what: str, index: int) -> DatasetKind:
    try:
        return DatasetKind(str(value))
    except ValueError:
        raise ParamError(f'Ряд {index}: неизвестный набор данных {value!r} ({what})') from None


def _date(value: Any, index: int) -> str:
    if value in (None, ''):
        return ''
    try:
        return pd.Timestamp(str(value)).strftime('%Y-%m-%d')
    except (TypeError, ValueError):
        raise ParamError(f'Ряд {index}: дата периода — ГГГГ-ММ-ДД') from None


def _x_transform(raw: Any, index: int) -> calc.Transform:
    t = calc.clean_transform(raw, index)
    if t.op not in X_OPS:
        raise ParamError(f'Ряд {index}: преобразование X — одно из: {", ".join(calc.TRANSFORMS[o] for o in X_OPS)}')
    return t


def _x_scope(value: Any, index: int) -> str:
    scope = str(value or 'curve')
    if scope not in X_SCOPES:
        raise ParamError(f'Ряд {index}: сводка X — {", ".join(X_SCOPES.values())}')
    return scope


def parse_layout(raw: Any) -> tuple[list[Row], dict[str, Any]]:
    """Ряды и ручные подписи из параметра ``layout``; неверное значение — ``ParamError`` с номером ряда."""
    layout = raw if isinstance(raw, Mapping) else {}
    rows = layout.get('series') or []
    if not isinstance(rows, list):
        raise ParamError('Макет: «series» — список рядов')
    out = []
    for i, r in enumerate(rows, start=1):
        if not isinstance(r, Mapping):
            raise ParamError(f'Ряд {i}: ожидается объект')
        source = str(r.get('source') or 'field')
        if source not in SOURCES:
            raise ParamError(f'Ряд {i}: источник — {" или ".join(SOURCES.values())}')
        if source == 'formula' and not r.get('dataset'):
            dataset = x_dataset = next(iter(DatasetKind))      # у формулы набор не нужен: данные — из рядов формулы
        else:
            dataset = _kind(r.get('dataset'), 'Y', i)
            x_dataset = _kind(r.get('x_dataset') or dataset.value, 'X', i)
        axis = str(r.get('axis') or 'y')
        view = str(r.get('view') or 'line')
        key = str(r.get('key') or 'well_date')
        if axis not in AXES:
            raise ParamError(f'Ряд {i}: ось — одна из Y1–Y5')
        if view not in VIEWS:
            raise ParamError(f'Ряд {i}: вид — {", ".join(VIEWS.values())}')
        if key not in KEYS:
            raise ParamError(f'Ряд {i}: ключ связи — {", ".join(KEYS.values())}')
        try:
            days = int(r.get('days', 3) if r.get('days') not in (None, '') else 3)
        except (TypeError, ValueError):
            raise ParamError(f'Ряд {i}: «±дней» — целое число') from None
        if not 0 <= days <= MAX_DAYS:
            raise ParamError(f'Ряд {i}: «±дней» — от 0 до {MAX_DAYS}')
        wells = r.get('wells') or []
        if not isinstance(wells, list):
            raise ParamError(f'Ряд {i}: скважины — список')
        out.append(Row(i, dataset, str(r.get('y') or ''), x_dataset, str(r.get('x') or 'date'), [str(w) for w in wells],
                       _date(r.get('date_from'), i), _date(r.get('date_to'), i), str(r.get('kind') or ''), axis, view, str(r.get('stack') or '').strip()[:60], key,
                       days, str(r.get('name') or '')[:200], bool(r.get('hidden')), clean_look(r.get('look'), i),
                       source, None, calc.clean_transform(r.get('transform'), i), str(r.get('unit') or '').strip()[:40],
                       'current' if str(r.get('wells_mode') or '') == 'current' else 'fixed',
                       _x_transform(r.get('x_transform'), i), _x_scope(r.get('x_scope'), i)))
    for row, r in zip(out, rows):
        text = str(r.get('formula') or '').strip()
        if row.source == 'formula' and text:
            row.formula = calc.parse_formula(text, row.index, len(out))
    calc.check_cycles({row.index: row.formula for row in out if row.formula is not None})
    axes = layout.get('axes') or {}
    labels = {'title': str(layout.get('title') or '')[:300], 'x_label': str(layout.get('x_label') or '')[:200],
              'axes': {a: str(axes.get(a) or '')[:200] for a in AXES} if isinstance(axes, Mapping) else {},
              'axis_style': clean_axes(layout.get('axis_style')), 'chart_style': clean_chart(layout.get('chart_style')),
              'current_well': str(layout.get('current_well') or '').strip()[:120]}
    return out, labels


PLACEHOLDER = '{скважина}'


def uses_current(layout: Any) -> bool:
    """В макете есть ряд в режиме «Текущая скважина»: такой макет переключается по скважинам и выгружается серией."""
    rows = layout.get('series') if isinstance(layout, Mapping) else None
    return any(isinstance(r, Mapping) and r.get('wells_mode') == 'current' for r in rows or [])


def _put_well(text: str, well: str) -> str:
    return text.replace(PLACEHOLDER, well or '…') if PLACEHOLDER in text else text


# ---------- выбор данных ----------

def _select(frame: pd.DataFrame, row: Row) -> pd.DataFrame:
    """Строки набора по скважинам (группам), режиму и периоду ряда."""
    d = frame
    entity = _entity(d)
    if entity and row.wells:
        if entity == 'group':
            keys = {group_key(w) for w in row.wells}
            d = d[d[entity].map(group_key).isin(keys)]
        else:
            d = d[d[entity].astype(str).isin(set(row.wells))]
    if row.kind and 'kind' in d:
        d = d[d['kind'].astype(str).eq(row.kind)]
    if 'date' in d and (row.date_from or row.date_to):
        dates = pd.to_datetime(d['date'], errors='coerce')
        keep = pd.Series(True, index=d.index)
        if row.date_from:
            keep &= dates >= pd.Timestamp(row.date_from)
        if row.date_to:
            keep &= dates < pd.Timestamp(row.date_to) + pd.Timedelta(days=1)
        d = d[keep]
    return d


def _day(values: pd.Series) -> pd.Series:
    """Дата без времени в одной точности (ns): наборы хранят даты в разной, ключи связи должны совпадать."""
    return pd.to_datetime(values, errors='coerce').dt.normalize().astype('datetime64[ns]')


def _values(frame: pd.DataFrame, kind: DatasetKind, column: str) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(frame[column]):
        return pd.to_datetime(frame[column], errors='coerce')
    return _numbers(frame[column]) * meta(kind, column).scale


@dataclass
class Pairs:
    frame: pd.DataFrame         # entity, x, y, id
    pairs: int                  # точек, где есть и X, и Y
    notes: list[Note]
    joined: bool                # X из другого набора или X обработан (накопленное, сводка по группе или объекту)
    x_label: str | None = None  # подпись X после преобразования; None — по полю


def pairs(data: Data, row: Row) -> Pairs:
    """Точки ряда: X и Y (из одного набора — построчно, из разных — по ключу связи ряда)."""
    notes: list[Note] = []
    label = f'Ряд {row.index}'
    empty = pd.DataFrame({'entity': [], 'x': [], 'y': [], 'id': []})
    for kind, column, what in ((row.dataset, row.y, 'Y'), (row.x_dataset, row.x, 'X')):
        if kind not in data or data[kind].empty:
            return Pairs(empty, 0, [Note(f'{label}: в проекте нет набора «{kind.label}» (поле {what}). Загрузите его в разделе импорта.')], False)
        if column not in data[kind] or _value_kind(data[kind][column]) is None:
            return Pairs(empty, 0, [Note(f'{label}: в наборе «{kind.label}» нет числового поля «{column}» ({what}). Выберите поле в дереве слева.', 'warning')], False)
    ys = _select(data[row.dataset], row)
    entity = _entity(data[row.dataset])
    y = pd.DataFrame({'entity': ys[entity].fillna('').astype(str) if entity else '', 'y': _values(ys, row.dataset, row.y),
                      'id': ys['_point_id'].astype(str) if '_point_id' in ys and row.dataset != K.ELPRO else None},
                     index=ys.index)
    if 'date' in ys:
        y['date'] = _day(ys['date'])
    prepared = row.x_scope != 'curve' or row.x_transform.op != 'none'
    joined = row.x_dataset != row.dataset or prepared
    x_label = None
    if not joined:
        y['x'] = _values(ys, row.dataset, row.x)
        out = y
    else:
        out, more, x_label = _join(data, row, y, entity)
        notes += more
    out = out[out['x'].notna()]
    if row.view == 'points':
        out = out[out['y'].notna()]
    count = int((out['x'].notna() & out['y'].notna()).sum())
    if joined:
        notes.append(Note(f'{label}: X «{meta(row.x_dataset, row.x).label}» ({row.x_dataset.label}) сопоставлен с Y '
                          f'по ключу «{_key_label(row)}» — найдено пар: {count}.'))
        if not count:
            notes += _hint_keys(data, row, y, entity)
    return Pairs(out.reset_index(drop=True), count, notes, joined, x_label)


def _hint_keys(data: Data, row: Row, y: pd.DataFrame, y_entity: str) -> list[Note]:
    """Пар нет: проверить остальные ключи связи и подсказать тот, при котором пары находятся (выбор остаётся за инженером)."""
    label = f'Ряд {row.index}'
    x, x_entity, _, _ = _x_side(data, row, label)
    if x.empty:
        return [Note(f'{label}: в X «{meta(row.x_dataset, row.x).label}» нет значений для выбранных скважин, периода и режима.', 'warning')]
    found = []
    for key in KEYS:
        if key == row.key:
            continue
        probe = replace(row, key=key, days=max(row.days, 30) if key == 'nearest' else row.days)
        out, notes = _merge(data, probe, y, y_entity, x, x_entity, label)
        if any(n.level == 'warning' for n in notes):
            continue
        count = int((out['x'].notna() & out['y'].notna()).sum()) if 'x' in out else 0
        if count:
            found.append(f'«{KEYS[key]}»{" ±" + str(probe.days) + " дн." if key == "nearest" else ""} — пар: {count}')
    hint = ('При другом ключе связи пары находятся: ' + '; '.join(found) + '. Выберите его в поле «Связь X и Y».') if found else \
        'Ни один ключ связи не даёт пар: у наборов нет общих скважин или дат. Проверьте периоды и режим ряда.'
    return [Note(f'{label}: нет ни одной пары X и Y. {hint}', 'warning')]


def _key_label(row: Row) -> str:
    return f'ближайшая дата ±{row.days} дн.' if row.key == 'nearest' else KEYS[row.key]


def _x_side(data: Data, row: Row, label: str) -> tuple[pd.DataFrame, str, str | None, list[Note]]:
    """Строки X-набора для связи: entity, x, date. Сводка по группе или объекту и преобразование X (накопленное и т. п.)
    считаются по строкам X-набора до связи с Y. Возвращает также подпись X после преобразования (None — по полю)."""
    notes: list[Note] = []
    frame = data[row.x_dataset]
    entity = _entity(frame)
    scope, t = row.x_scope, row.x_transform
    # свод по группе и объекту берёт скважины набора целиком; период ряда режет и Y, и X (накопленное идёт с начала периода)
    xs = _select(frame, replace(row, wells=[]) if scope != 'curve' else row)
    x = pd.DataFrame({'entity': xs[entity].fillna('').astype(str) if entity else '', 'x': _values(xs, row.x_dataset, row.x)}, index=xs.index)
    if 'date' in xs:
        x['date'] = _day(xs['date'])
    x = x[x['x'].notna()]
    if entity == 'group':
        x['entity'] = x['entity'].map(group_key)
    if scope == 'curve' and t.op == 'none':
        return x, entity, None, notes
    m = meta(row.x_dataset, row.x)
    if pd.api.types.is_datetime64_any_dtype(x['x']) or 'date' not in x:
        notes.append(Note(f'{label}: сводка и преобразование X работают только для числового поля с датами; X оставлен как в наборе.', 'warning'))
        return x, entity, None, notes
    kinds = frame['kind'].dropna().astype(str).nunique() if 'kind' in frame else 0
    if scope != 'curve' and kinds > 1 and not row.kind:
        notes.append(Note(f'{label}: в наборе «{row.x_dataset.label}» отбор и закачка вместе — выберите «Режим» в ряду, '
                          'иначе в сводку X попадут оба.', 'warning'))
    out_entity = entity
    if scope in ('group', 'object'):
        x = x.dropna(subset=['date'])
        wells = x['entity'].nunique() if entity else 0
        additive = m.unit in calc.CUMULATIVE or m.unit.endswith('/сут')
        how = 'sum' if additive else 'mean'
        if scope == 'group':
            if entity == 'well':
                groups = data.mapping
                x['entity'] = x['entity'].map(lambda w: group_key(groups.get(w, {}).get('group') or 'Без группы'))
            elif entity == 'group':
                x['entity'] = x['entity'].map(group_key)
            else:
                notes.append(Note(f'{label}: в наборе «{row.x_dataset.label}» нет ни скважин, ни групп — сводка по группе не нужна, X как в наборе.'))
                scope = 'curve'
        if scope == 'group':
            out_entity = 'group'
            by = ['entity', 'date']
        else:
            x['entity'] = ''
            out_entity = ''
            by = ['date']
        if scope != 'curve':
            agg = x.groupby(by, sort=True)['x'].sum(min_count=1) if how == 'sum' else x.groupby(by, sort=True)['x'].mean()
            x = agg.reset_index()
            if 'entity' not in x:
                x['entity'] = ''
            notes.append(Note(f'{label}: X «{m.label}» — {"сумма" if how == "sum" else "среднее"} по '
                              f'{"группе скважины" if scope == "group" else "объекту"}'
                              f'{f" ({wells} скв. набора)" if wells else ""}.'))
    new_label = m.label + (f', {m.unit}' if m.unit else '')
    if t.op != 'none':
        f = pd.DataFrame({'entity': x['entity'], 'x': x['date'], 'y': x['x']})
        f, more = calc.apply(f, t, m.unit, f'{label}, X', True, _seasons(data, row) if t.season else None)
        notes += more
        word = 'группам' if out_entity == 'group' else 'скважинам'
        text, unit = calc.describe(t, m.label, m.unit, word)
        new_label = text + (f', {unit}' if unit else '')
        x = pd.DataFrame({'entity': f['entity'], 'x': f['y'], 'date': f['x']})
        x = x[x['x'].notna()]
    where = {'group': ', по группе', 'object': ', по объекту'}.get(row.x_scope, '')
    return x, out_entity, new_label + where, notes


def _seasons(data: Data, row: Row) -> pd.Series | None:
    """Сезон каждых суток (дата → период расхода, как в «Сезонных показателях»); нейтральные периоды и сутки без периода не входят."""
    frame = data[K.PRODUCTION] if K.PRODUCTION in data else None
    if frame is None or 'period' not in frame or 'date' not in frame:
        return None
    if row.kind and 'kind' in frame:
        frame = frame[frame['kind'].astype(str).eq(row.kind)]
    frame = frame.dropna(subset=['period', 'date'])
    frame = frame[~frame['period'].astype(str).str.startswith(NEUTRAL_PREFIXES)]
    return frame.assign(date=_day(frame['date'])).drop_duplicates('date').set_index('date')['period'].astype(str) if len(frame) else None


def _y_group_keys(data: Data, y: pd.DataFrame, y_entity: str) -> pd.Series:
    if y_entity == 'well':
        return y['entity'].map(lambda w: group_key(data.mapping.get(w, {}).get('group') or 'Без группы'))
    return y['entity'].map(group_key)


def _join(data: Data, row: Row, y: pd.DataFrame, y_entity: str) -> tuple[pd.DataFrame, list[Note], str | None]:
    """X из другого набора (или обработанный X) на строки Y по ключу ряда. Несколько значений X на ключ — среднее (дата — первая)."""
    label = f'Ряд {row.index}'
    x, x_entity, x_label, notes = _x_side(data, row, label)
    out, more = _merge(data, row, y, y_entity, x, x_entity, label)
    return out, notes + more, x_label


def _merge(data: Data, row: Row, y: pd.DataFrame, y_entity: str, x: pd.DataFrame, x_entity: str, label: str) -> tuple[pd.DataFrame, list[Note]]:
    notes: list[Note] = []
    by_group = row.x_scope == 'group' and x_entity == 'group' and y_entity in ('well', 'group')
    shared = bool(y_entity) and (y_entity == x_entity or by_group)
    has_dates = 'date' in y and 'date' in x
    key = row.key
    if row.x_scope == 'object' and key == 'well_date':
        key = 'date'                       # X один на весь объект: скважину для связи брать не из чего
    if row.x_scope == 'object' and key == 'well':
        notes.append(Note(f'{label}: X — сумма по объекту, у неё нет скважин. Выберите ключ «дата» или «ближайшая дата».', 'warning'))
        return y.iloc[0:0].assign(x=np.nan), notes
    if key in ('well_date', 'well') and not shared:
        if key == 'well' or not has_dates:
            notes.append(Note(f'{label}: у наборов «{row.dataset.label}» и «{row.x_dataset.label}» нет общей колонки скважин — '
                              'сопоставить по скважине нельзя. Выберите ключ «дата».', 'warning'))
            return y.iloc[0:0].assign(x=np.nan), notes
        notes.append(Note(f'{label}: в наборе «{row.x_dataset.label}» нет скважин — X сопоставлен только по дате.'))
        key = 'date'
    if key in ('well_date', 'date', 'nearest') and not has_dates:
        notes.append(Note(f'{label}: в одном из наборов нет дат — выберите ключ «скважина».', 'warning'))
        return y.iloc[0:0].assign(x=np.nan), notes
    y_key = y.assign(entity=_y_group_keys(data, y, y_entity)) if by_group or y_entity == 'group' else y
    if key == 'nearest':
        by = ['entity'] if shared else []
        left = y_key[y_key['date'].notna()].reset_index().sort_values('date', kind='stable')
        right = _aggregate(x[x['date'].notna()], by + ['date'], notes, label).sort_values('date', kind='stable')
        merged = pd.merge_asof(left, right.drop(columns=[] if shared else ['entity'], errors='ignore'), on='date', by=by or None,
                               tolerance=pd.Timedelta(days=row.days), direction='nearest')
        merged = merged.set_index('index').sort_index()
        merged.index.name = None
        out = y.join(merged[['x']])
        return out, notes
    on = {'well_date': ['entity', 'date'], 'date': ['date'], 'well': ['entity']}[key]
    right = _aggregate(x, on, notes, label)
    merged = y_key.drop(columns=['x'], errors='ignore').reset_index().merge(right, on=on, how='left').set_index('index')
    merged.index.name = None
    return y.join(merged[['x']]), notes


def _aggregate(x: pd.DataFrame, on: list[str], notes: list[Note], label: str) -> pd.DataFrame:
    x = x.dropna(subset=[c for c in on if c == 'date'])
    if not x.duplicated(on).any():
        return x[on + ['x']]
    if pd.api.types.is_datetime64_any_dtype(x['x']):
        out = x.groupby(on, sort=False, as_index=False)['x'].first()
    else:
        out = x.groupby(on, sort=False, as_index=False)['x'].mean()
    notes.append(Note(f'{label}: на один ключ приходится несколько значений X — взято среднее '
                      f'({len(x) - len(out)} строк объединено).'))
    return out


# ---------- график ----------

def _join_labels(values: list[str]) -> str:
    unique = list(dict.fromkeys(v for v in values if v))
    return ', '.join(unique[:3]) + (' …' if len(unique) > 3 else '')


def _series_name(row: Row, base: str, entity_kind: str, entity: str, many: bool) -> str:
    base = row.name or base
    if row.kind and not row.name and row.source == 'field':
        base += f' ({KINDS.get(row.kind, row.kind).lower()})'
    if not entity_kind or not entity or (row.name and not many):
        return base
    return f'{base} · скв. {entity}' if entity_kind == 'well' else f'{base} · {entity}'


@dataclass
class Calc:
    """Посчитанный ряд: точки после преобразования, подпись и единица Y, подпись X."""
    frame: pd.DataFrame
    entity_kind: str
    label: str
    unit: str
    x_label: str


def _no_well(row: Row) -> bool:
    """Ряд «Текущая скважина», а скважина не выбрана: пустой список скважин означал бы «все», поэтому ряд не считается."""
    return row.well_mode == 'current' and not row.wells


def _calc_row(data: Data, row: Row, rows: dict[int, Row], cache: dict[int, Calc | None], notes: list[Note]) -> Calc | None:
    """Ряд по полю или формуле с преобразованием; ряды формулы (в том числе скрытые) считаются один раз."""
    if row.index in cache:
        return cache[row.index]
    cache[row.index] = None
    out: Calc | None = None
    if _no_well(row):
        return None
    if row.source == 'formula':
        if row.formula is None:
            return None
        parts: dict[int, calc.Part | None] = {}
        refs: dict[int, Calc | None] = {}
        for i in row.formula.refs:
            refs[i] = _calc_row(data, rows[i], rows, cache, notes)
            parts[i] = calc.Part(refs[i].frame, refs[i].entity_kind) if refs[i] else None
        part, more = calc.compute(row.formula, parts, row.key, row.days, row.index)
        notes += more
        base = refs[row.formula.refs[0]]
        if part is not None and base is not None:
            out = Calc(part.frame, part.entity_kind, row.formula.text, '', base.x_label)
    elif row.y:
        p = pairs(data, row)
        notes.extend(p.notes)
        m, xm = meta(row.dataset, row.y), meta(row.x_dataset, row.x)
        entity = _entity(data[row.dataset]) if row.dataset in data else ''
        out = Calc(p.frame, entity, m.label, m.unit, p.x_label or xm.label + (f', {xm.unit}' if xm.unit else ''))
    if out is not None and not out.frame.empty:
        word = 'группам' if out.entity_kind == 'group' else 'скважинам'
        out.label, out.unit = calc.describe(row.transform, out.label, out.unit, word)
        x_date = pd.api.types.is_datetime64_any_dtype(out.frame['x'])
        before = '' if row.source == 'formula' else meta(row.dataset, row.y).unit     # у формулы единица — только ручная
        out.frame, more = calc.apply(out.frame, row.transform, before, f'Ряд {row.index}', x_date,
                                     _seasons(data, row) if row.transform.season else None)
        notes += more
        if row.transform.op == 'group':
            out.entity_kind = ''
    if out is not None and row.unit:
        out.unit = row.unit
    cache[row.index] = out
    return out


def build(data: Data, layout: Any, well: str | None = None) -> Result:
    """График макета. ``well`` — скважина для рядов «Текущая скважина» (иначе ``layout.current_well``); {скважина} в подписях заменяется ею."""
    rows, labels = parse_layout(layout)
    well = str(well if well is not None else labels['current_well']).strip()
    labels['title'] = _put_well(labels['title'], well)
    labels['x_label'] = _put_well(labels['x_label'], well)
    labels['axes'] = {a: _put_well(t, well) for a, t in labels['axes'].items()}
    result = Result()
    for r in rows:
        r.name = _put_well(r.name, well)
        if r.well_mode == 'current' and not r.hidden and r.source == 'field' and r.dataset in data and _entity(data[r.dataset]) == 'group':
            r.hidden = True
            result.notes.append(Note(f'Ряд {r.index}: набор «{r.dataset.label}» — по группам, а не по скважинам; режим «Текущая скважина» к нему '
                                     'не применяется. Ряд не показан: выберите «фиксированные скважины» (группы) в карточке ряда.', 'warning'))
        elif r.well_mode == 'current':
            r.wells = [well] if well else []
            if not well and not r.hidden:
                result.notes.append(Note(f'Ряд {r.index}: не выбрана скважина макета — выберите её над рядами.', 'warning'))
    shown = [r for r in rows if not r.hidden]
    if not shown:
        result.notes.append(Note('Добавьте ряд: выберите поле в дереве слева или нажмите «+ Добавить ряд».'))
        return result
    for r in shown:
        if r.source == 'field' and not r.y:
            result.notes.append(Note(f'Ряд {r.index}: выберите поле Y в дереве слева.'))
        if r.source == 'formula' and r.formula is None:
            result.notes.append(Note(f'Ряд {r.index}: введите формулу по рядам, например A/B или (A-B)/A*100.'))
    shown = [r for r in shown if (r.y if r.source == 'field' else r.formula) and not _no_well(r)]
    by_index = {r.index: r for r in rows}
    cache: dict[int, Calc | None] = {}
    built: list[tuple[Row, Calc]] = []
    x_kind: str | None = None
    x_labels: list[str] = []
    for r in shown:
        c = _calc_row(data, r, by_index, cache, result.notes)
        if c is None or c.frame.empty:
            if r.source == 'field':
                result.notes.append(Note(f'Ряд {r.index} «{meta(r.dataset, r.y).label}»: нет точек с выбранными скважинами, '
                                         'периодом и режимом. Расширьте выбор.'))
            elif c is not None:
                result.notes.append(Note(f'Ряд {r.index}: у формулы «{r.formula.text}» нет точек.'))
            continue
        kind = 'date' if pd.api.types.is_datetime64_any_dtype(c.frame['x']) else 'number'
        if x_kind is None:
            x_kind = kind
        elif kind != x_kind:
            result.notes.append(Note(f'Ряд {r.index}: X — {"дата" if kind == "date" else "число"}, а у первого ряда — '
                                     f'{"дата" if x_kind == "date" else "число"}; на одном графике ось X одна. '
                                     'Ряд не показан: выберите для него X того же вида.', 'warning'))
            continue
        x_labels.append(c.x_label)
        built.append((r, c))
    if not built:
        return result

    used = sorted({r.axis for r, _ in built}, key=AXES.index)
    place = {a: AXES[i] for i, a in enumerate(used)}      # шкалы идут подряд: Y3 без Y2 — вторая, Y2 без Y1 — левая
    moved = [a for a in used if place[a] != a]
    if moved:
        empty = [a for a in AXES[:AXES.index(used[-1])] if a not in used]
        result.notes.append(Note(f'Ось {", ".join(_axis_title(a) for a in empty)} пуста — ряды осей '
                                 f'{", ".join(_axis_title(a) for a in moved)} показаны на шкалах ближе к графику.'))

    axes: dict[str, Axis] = {}
    for a in used:
        on_axis = [c for r, c in built if r.axis == a]
        units = {c.unit for c in on_axis}
        manual = labels['axes'].get(a, '')
        is_time = any(pd.api.types.is_datetime64_any_dtype(c.frame['y']) for c in on_axis)
        axes[place[a]] = Axis(manual or _join_labels([c.label for c in on_axis]) or 'Значение',
                              '' if manual or len(units) != 1 else units.pop(), scale='time' if is_time else 'value')

    x_axis = Axis(labels['x_label'] or _join_labels(x_labels) or 'X', scale='time' if x_kind == 'date' else 'value')
    if labels['x_label'] or x_kind == 'date':
        x_axis.unit = ''
    values = {'x': [p.frame['x'] for _, p in built], **{a: [p.frame['y'] for r, p in built if r.axis == a] for a in used}}
    for name, spec in labels['axis_style'].items():
        if name == 'x' or name in place:
            _style_axis(x_axis if name == 'x' else axes[place[name]], spec, 'X' if name == 'x' else _axis_title(name), values[name], result.notes)
    title = labels['title'] or _join_labels([r.name or c.label for r, c in built])
    chart = Chart('builder', title, x_axis, axes['y'], crosshair=x_kind == 'date',
                  y2=axes.get('y2'), y3=axes.get('y3'), y4=axes.get('y4'), y5=axes.get('y5'), style=labels['chart_style'])
    total = 0
    items: list[tuple[Row, str, str, pd.DataFrame]] = []
    label_of = {r.index: c.label for r, c in built}
    for r, p in built:
        entity_kind = p.entity_kind
        groups = [(e, g) for e, g in p.frame.groupby('entity', sort=False)] if entity_kind else [('', p.frame)]
        groups.sort(key=lambda eg: natural_key(eg[0]))
        for entity, g in groups:
            g = g.sort_values('x', kind='stable')
            if r.view in BROKEN and x_kind == 'date':
                g = _break_gaps(g)
            items.append((r, entity_kind, str(entity), g))
    stacks = _stack_names(built, place, result.notes)
    union: dict[str, pd.Index] = {}      # стопка складывается по номеру точки: у всех её рядов общий список X
    for r, _, _, g in items:
        if r.index in stacks:
            union[stacks[r.index]] = union.get(stacks[r.index], pd.Index([])).union(pd.Index(g['x'].dropna().unique()))
    per_row = {r.index: sum(1 for o, *_ in items if o.index == r.index) for r, *_ in items}
    for r, entity_kind, entity, g in items:
        stack = stacks.get(r.index, '')
        if stack:
            g = _on_grid(g, union[stack])
        points = int(g['y'].notna().sum())
        total += points
        name = _series_name(r, label_of[r.index], entity_kind, entity, per_row[r.index] > 1)
        facets = {'Ряд': f'{r.index}. {r.name or label_of[r.index]}'}
        if entity_kind and entity:
            facets['Скважина' if entity_kind == 'well' else 'Группа'] = f'№ {entity}' if entity_kind == 'well' else entity
        ids = g['id'].tolist() if g['id'].notna().all() and len(g) else None
        kind = 'points' if r.view == 'points' else 'bar' if r.view == 'bar' else 'line'
        chart.series.append(Series(
            name, g['x'].to_numpy(), g['y'].to_numpy(), kind,
            group=f'{r.index}:{entity}', axis=place[r.axis], markers=kind == 'line' and r.view in ('line', 'step') and points <= SPARSE,
            ids=ids, dataset=r.dataset if ids else None, facets=facets, stack=stack,
            fill=r.view == 'area', step=r.view == 'step'))
        _style_series(chart.series[-1], r.look, r.view)
    for key, axis in axes.items():      # столбцы и области растут от нуля: шкала с нулём, если границу не задали вручную
        if axis.scale == 'value' and axis.minimum is None and any(
                s.axis == key and (s.kind == 'bar' or s.fill) for s in chart.series):
            axis.from_zero = True
    result.charts.append(chart)
    if len(chart.series) > MANY_SERIES:
        result.notes.append(Note(f'На графике {len(chart.series)} кривых — его трудно читать. Выберите меньше скважин в рядах.', 'warning'))
    result.summary = [Stat('Рядов', str(len(built))), Stat('Кривых', str(len(chart.series))),
                      Stat('Точек', f'{total:,}'.replace(',', ' '), 'точки, где есть и X, и Y')]
    return result


def _style_series(s: Series, look: dict[str, Any], view: str = 'line') -> None:
    """Ручной вид ряда: на экране и в выгрузке действует ``Series.look``; прозрачность и маркеры линии — и в полях серии.
    «Линия с точками» всегда с маркерами (если не выключены вручную); у области и столбцов прозрачность относится к заливке."""
    look = dict(look)
    if view == 'line_points':
        look.setdefault('marker', True)       # не через ``markers``: плотная линия сглаживается без отметок
    if look:
        s.look = look
    if 'opacity' in look and not (s.fill or s.kind == 'bar'):
        s.opacity = look['opacity']
    if s.kind == 'line' and 'marker' in look and view != 'line_points':
        s.markers = look['marker']


def _style_axis(axis: Axis, spec: dict[str, Any], title: str, values: list[pd.Series], notes: list[Note]) -> None:
    """Ручные границы, шаг, логарифм, направление и оформление оси; то, что к оси не подходит, пропускается с заметкой."""
    time = axis.scale == 'time'
    if 'color' in spec:
        axis.color = spec['color']
    axis.style = {k: v for k, v in spec.items() if k in ('decimals', 'date_format', 'font', 'tick_size', 'title_size')}
    if spec.get('inverse'):
        axis.inverse = True
    if spec.get('from_zero') and axis.scale == 'value':
        axis.from_zero = True
    low = bound(spec['min'], f'Ось {title}, минимум', time) if 'min' in spec else None
    high = bound(spec['max'], f'Ось {title}, максимум', time) if 'max' in spec else None
    if low is not None and high is not None and low >= high:
        raise ParamError(f'Ось {title}: минимум должен быть меньше максимума')
    if spec.get('log'):
        positive = all((v.dropna() > 0).all() for v in values if not pd.api.types.is_datetime64_any_dtype(v))
        if time:
            notes.append(Note(f'Ось {title}: логарифмическая шкала не применяется к датам.'))
        elif not positive or (low is not None and low <= 0):
            notes.append(Note(f'Ось {title}: логарифмическая шкала возможна только для положительных значений — оставлена линейная.'))
        else:
            axis.scale = 'log'
    axis.minimum, axis.maximum = low, high
    if 'step' in spec:
        if axis.scale not in ('value', 'log'):
            notes.append(Note(f'Ось {title}: шаг делений задаётся для чисел; у дат деления подбираются сами.'))
        else:
            axis.step = bound(spec['step'], f'Ось {title}, шаг', False)
            if axis.step <= 0:
                raise ParamError(f'Ось {title}, шаг: больше нуля')


BROKEN = ('line', 'line_points', 'area', 'step')      # виды с линией: по датам рвётся на перерывах


def _stack_names(built: list[tuple[Row, Any]], place: dict[str, str], notes: list[Note]) -> dict[int, str]:
    """Имя стопки по номеру ряда (только столбцы и области). Столбцы и области, а также разные шкалы Y складываются раздельно:
    одинаковое имя на них разводится суффиксом, об этом заметка."""
    groups: dict[str, set[tuple[str, str]]] = {}
    for r, _ in built:
        if r.stack and r.view in STACKABLE:
            groups.setdefault(r.stack, set()).add((r.view, place[r.axis]))
    out = {}
    for r, _ in built:
        if not r.stack:
            continue
        if r.view not in STACKABLE:
            notes.append(Note(f'Ряд {r.index}: стопка «{r.stack}» задана для вида «{VIEWS[r.view]}» — она действует только у столбцов и областей.'))
        elif len(groups[r.stack]) > 1:
            out[r.index] = f'{r.stack} · {VIEWS[r.view]} · {_axis_title(place[r.axis])}'
        else:
            out[r.index] = r.stack
    for name, parts in groups.items():
        if len(parts) > 1:
            notes.append(Note(f'Стопка «{name}»: столбцы и области, а также ряды разных осей складываются отдельно друг от друга.'))
    return out


def _on_grid(g: pd.DataFrame, grid: pd.Index) -> pd.DataFrame:
    """Ряд на общем списке X стопки: где у ряда нет точки — пропуск."""
    out = g.drop_duplicates('x').set_index('x').reindex(grid.sort_values())
    out['entity'] = g['entity'].iloc[0] if len(g) else ''
    return out.rename_axis('x').reset_index()


def _break_gaps(g: pd.DataFrame) -> pd.DataFrame:
    """Разрыв линии там, где записей нет дольше обычного (между сезонами, при выборе одного режима):
    иначе линия соединила бы далёкие даты прямой. Сутки с нулём — запись, разрыва нет."""
    if len(g) < 3:
        return g
    step = g['x'].diff()
    limit = max(pd.Timedelta(days=GAP_DAYS), step.median() * GAP_STEPS)
    at = step.index[step.gt(limit).to_numpy()]
    if not len(at):
        return g
    breaks = pd.DataFrame({'entity': g.loc[at, 'entity'].to_numpy(), 'x': (g['x'].shift().loc[at] + step.loc[at] / 2).to_numpy(),
                           'y': np.nan, 'id': '' if g['id'].notna().all() else None})
    return pd.concat([g, breaks], ignore_index=True).sort_values('x', kind='stable')


def _axis_title(name: str) -> str:
    return 'Y1' if name == 'y' else 'Y' + name[1:]


class ChartBuilder(Module):
    spec = ModuleSpec(
        id='builder', title='Конструктор графиков', group='Графики', order=95,
        description='Свой график из любых полей проекта: ряды, оси Y1–Y5, X — дата или число.',
        optional=tuple(DatasetKind),
        params=(Param('layout', 'Макет', 'json', default=DEFAULT_LAYOUT,
                      help='Ряды графика, ручные подписи осей и заголовок'),),
        save_label='Сохранить макет',
    )

    def run(self, data: Data, params: dict[str, Any]) -> Result:
        return build(data, params.get('layout'))

    def catalog(self, data: Data) -> dict[str, Any]:
        return catalog(data)
