"""Контракт модуля Gas Atlas 6.

Модуль — класс с декларативным ``spec`` и чистым методом ``run(data, params) -> Result``.
Интерфейс не импортирует модули: он читает ``GET /api/modules`` и строит панель параметров
и вывод обобщённо. Всё, что модуль хочет показать, выражается типами из этого файла.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re
from dataclasses import asdict, dataclass, field, fields
from typing import Any, ClassVar, Literal, Mapping, Sequence

import numpy as np
import pandas as pd

from .domain import DatasetKind

ParamKind = Literal['number', 'integer', 'boolean', 'choice', 'multi', 'date', 'text', 'map', 'file', 'json']
JSON_LIMIT = 200_000      # json: предел размера значения, символов


from atlas.engine.core.config import DataRangeError  # noqa: E402,F401  (перевыпуск для api)


class ParamError(ValueError):
    """Неверное значение параметра; текст показывается пользователю как есть."""


_END_NAMES = ('end', 'stop', 'date_to', 'cubes_to', 'model_cubes_to')


def is_end_param(name: str) -> bool:
    """Параметр — правая граница периода («по», «конец»): неполная дата округляется до конца периода."""
    return name in _END_NAMES or name.endswith('_to') or name.endswith('_end')


def parse_partial_date(value: Any, end: bool = False) -> str:
    """Дата с неполными частями → 'ГГГГ-ММ-ДД'. «2020» — 01.01.2020 (начало) или 31.12.2020 (конец),
    «03.2020» / «2020-03» — 01.03 или 31.03. Полная дата берётся как есть. Единый разбор для всех фильтров периода."""
    text = str(value).strip()
    m = re.fullmatch(r'(\d{4})', text)
    if m:
        year, month = int(m[1]), None
    else:
        m = re.fullmatch(r'(\d{4})[-./](\d{1,2})', text) or re.fullmatch(r'(\d{1,2})[-./](\d{4})', text)
        if m:
            a, b = int(m[1]), int(m[2])
            year, month = (a, b) if m[1] and len(m[1]) == 4 else (b, a)
        else:
            d = re.fullmatch(r'(\d{1,2})[./](\d{1,2})[./](\d{4})', text)
            return (dt.date(int(d[3]), int(d[2]), int(d[1])).isoformat() if d else pd.Timestamp(text).strftime('%Y-%m-%d'))
    if month is not None and not 1 <= month <= 12:
        raise ValueError(text)
    if month is None:
        return f'{year:04d}-12-31' if end else f'{year:04d}-01-01'
    start = pd.Timestamp(year=year, month=month, day=1)
    return (start + pd.offsets.MonthEnd(0) if end else start).strftime('%Y-%m-%d')


@dataclass(frozen=True)
class Option:
    value: Any
    label: str


@dataclass(frozen=True)
class Source:
    """Варианты выбора берутся из данных проекта: уникальные значения колонки набора."""
    dataset: DatasetKind
    column: str


@dataclass(frozen=True)
class Param:
    name: str
    label: str
    kind: ParamKind
    default: Any = None
    help: str = ''
    formula: str = ''                 # как считается (кнопка «?» у параметра): формула или правило одной строкой
    example: str = ''                 # числовой пример к формуле
    options: tuple[Option, ...] = ()
    source: Source | None = None      # для choice/multi: варианты из данных
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    unit: str = ''
    setting: str | None = None        # общая настройка проекта (manifest.settings), напр. 'r2_threshold'
    section: str = ''                 # группа на панели параметров: 'Выбор данных', 'Вид'
    dynamic: bool = False             # варианты вычисляет модуль: Module.options(name, data, params)
    depends: tuple[str, ...] = ()     # от каких параметров зависят варианты (пересчитываются при их смене)
    auto: str = ''                    # выбор по умолчанию из вариантов: 'all' | 'first:10' | 'last:3'
    prefix: str = ''                  # приставка к подписи варианта на экране, например '№ '
    requires_dataset: str = ''        # параметр скрыт, пока в проекте нет этого набора данных, напр. 'elpro'
    empty: str = 'все'                # что значит пустой выбор в списке: 'все' или 'ничего'
    show_if: dict[str, Any] | None = None   # показывать, только если параметры равны этим значениям
    aliases: Mapping[str, Any] = field(default_factory=dict)   # старое значение choice → нынешнее (сохранённые виды и проекты открываются)
    chart_kind: bool = False          # переключатель вида графиков: выводится в верхнем тулбаре раздела
    extensions: str = ''              # для file: расширения в проводнике, через пробел: 'xlsx docx'
    wells_picker: bool = False        # список скважин: пресеты (группы, фонды, сетка), вставка из буфера обмена

    def coerce(self, value: Any) -> Any:
        if value is None or (self.kind == 'date' and value == ''):
            return self.default
        try:
            if self.kind == 'boolean':
                if isinstance(value, str):
                    return value.lower() in ('1', 'true', 'да', 'yes')
                return bool(value)
            if self.kind in ('number', 'integer'):
                number = float(value)
                if not math.isfinite(number):
                    raise ValueError
                if self.kind == 'integer':
                    if number != int(number):
                        raise ValueError
                    number = int(number)
                if self.minimum is not None and number < self.minimum:
                    raise ParamError(f'«{self.label}»: значение меньше {self.minimum:g}')
                if self.maximum is not None and number > self.maximum:
                    raise ParamError(f'«{self.label}»: значение больше {self.maximum:g}')
                return number
        except ParamError:
            raise
        except (TypeError, ValueError):
            raise ParamError(f'«{self.label}»: ожидается {"целое " if self.kind == "integer" else ""}число') from None
        if self.kind == 'date':
            try:
                return parse_partial_date(value, is_end_param(self.name))
            except (TypeError, ValueError):
                raise ParamError(f'«{self.label}»: ожидается дата ГГГГ-ММ-ДД, ММ.ГГГГ или год') from None
        if self.kind == 'text':
            return str(value)[:5000]
        if self.kind == 'file':    # путь к файлу, выбранному общим проводником; существование проверяет модуль
            return str(value).strip().strip('"').strip()[:1000]
        if self.kind == 'choice':
            value = self.aliases.get(value, value) if isinstance(value, str) else value
            if self.options and value not in {o.value for o in self.options}:
                raise ParamError(f'«{self.label}»: недопустимое значение {value!r}')
            return value
        if self.kind == 'multi':
            if not isinstance(value, (list, tuple)):
                raise ParamError(f'«{self.label}»: ожидается список')
            values = [str(v) for v in value]
            if self.options:
                allowed = {str(o.value) for o in self.options}
                bad = [v for v in values if v not in allowed]
                if bad:
                    raise ParamError(f'«{self.label}»: недопустимые значения {", ".join(bad[:5])}')
            return values
        if self.kind == 'map':     # ключ → число; пустые значения отбрасываются
            if not isinstance(value, Mapping):
                raise ParamError(f'«{self.label}»: ожидается словарь')
            out = {}
            for key, item in value.items():
                if item is None or item == '':
                    continue
                try:
                    number = float(item)
                except (TypeError, ValueError):
                    raise ParamError(f'«{self.label}»: «{key}» — ожидается число') from None
                if not math.isfinite(number) or (self.minimum is not None and number < self.minimum):
                    raise ParamError(f'«{self.label}»: «{key}» — число не меньше {self.minimum or 0:g}')
                out[str(key)] = number
            return out
        if self.kind == 'json':    # объект или список (макет раздела); проверяет модуль, здесь — только форма и размер
            if not isinstance(value, (Mapping, list)):
                raise ParamError(f'«{self.label}»: ожидается объект JSON')
            try:
                text = json.dumps(value, ensure_ascii=False, allow_nan=False)
            except (TypeError, ValueError):
                raise ParamError(f'«{self.label}»: значение не переводится в JSON') from None
            if len(text) > JSON_LIMIT:
                raise ParamError(f'«{self.label}»: слишком большое значение (больше {JSON_LIMIT} символов)')
            return json.loads(text)
        raise ParamError(f'Неизвестный тип параметра {self.kind}')


BUILDER_LAYOUTS = 'builder_layouts'


def builder_layouts_param(label: str = 'Макеты конструктора', help: str = '') -> 'Param':
    """Параметр «Макеты конструктора»: имена сохранённых макетов проекта (варианты — ``Module.options``)."""
    return Param(BUILDER_LAYOUTS, label, 'multi', default=[], dynamic=True, empty='ничего', section='Вид',
                 help=help or 'Сохранённые макеты «Конструктора графиков» проекта: графики добавляются после основных. '
                              'Макет «Текущая скважина» строится по каждой выбранной скважине.')


@dataclass(frozen=True)
class ModuleSpec:
    id: str                          # стабильный идентификатор, латиница: 'gdi'
    title: str                       # 'ГДИ: индикаторные диаграммы'
    group: str                       # раздел навигации: 'Исследования скважин'
    description: str = ''
    needs: tuple[DatasetKind, ...] = ()          # обязательные наборы данных
    optional: tuple[DatasetKind, ...] = ()       # используются, если есть
    params: tuple[Param, ...] = ()
    auto_run: bool = True            # пересчитывать сразу при изменении параметров
    order: int = 100                 # порядок в навигации
    panels: int = 1                  # сколько независимых панелей можно открыть рядом (2 — «две панели»)
    save_label: str = 'Сохранить фильтры'   # подпись кнопки сохранения вида
    builder_layouts: bool = False    # раздел принимает макеты «Конструктора графиков» (параметр builder_layouts добавляется сам)

    def __post_init__(self) -> None:
        if self.builder_layouts and not any(p.name == BUILDER_LAYOUTS for p in self.params):
            object.__setattr__(self, 'params', (*self.params, builder_layouts_param()))

    def coerce(self, raw: Mapping[str, Any] | None) -> dict[str, Any]:
        raw = dict(raw or {})
        unknown = set(raw) - {p.name for p in self.params}
        if unknown:
            raise ParamError(f'Неизвестные параметры: {", ".join(sorted(unknown))}')
        return {p.name: p.coerce(raw.get(p.name)) for p in self.params}

    def to_json(self) -> dict[str, Any]:
        out = asdict(self)
        out['needs'] = [k.value for k in self.needs]
        out['optional'] = [k.value for k in self.optional]
        for p in out['params']:
            if p['source']:
                p['source']['dataset'] = p['source']['dataset'].value
        return out


# ---------- результат ----------

@dataclass
class Column:
    key: str
    label: str
    unit: str = ''
    decimals: int | None = None      # None — показывать как есть
    kind: Literal['text', 'number', 'date'] = 'text'
    good: float | None = None        # порог «хорошо»: значение ≥ порога — зелёным, ниже — красным


@dataclass(frozen=True)
class TableAction:
    """Действие над строками таблицы и кнопка применения.

    ``exclude`` — флажки исключения точек: ``id_column`` — идентификатор точки (``_point_id``);
    ``checked_column`` — колонка с текущим состоянием (снятый флажок восстанавливает точку).
    Без неё флажки только добавляют исключения.

    ``assign`` — назначение групп скважин: ``id_column`` — скважина, ``fields`` — колонки, которые
    уходят в проект (``group``, ``subgroup``), ``editable`` — какие из них правятся в ячейках.
    ``submit='all'`` отправляет все строки как есть (автоматические подгруппы), ``'changed'`` — только изменённые.
    ``journal`` — запись в журнале проекта. ``target`` — куда уходят назначения: ``groups`` (группы скважин)
    ``object-categories`` (категории объектов кроссплота; ``id_column`` — объект, поле ``category``) или
    ``well-categories`` (ручные категории скважин фонда по сезонам; ``id_column`` — скважина, поле ``category``) или
    ``wf-status`` (ручные ячейки таблицы ВФ; ``id_column`` — «скважина|сезон», поле ``manual``) или
    ``gis-comments`` (подписи к столбцам плитки ГИС; ``id_column`` — «скважина|пачка|сезон», поле ``comment``).
    """
    kind: Literal['exclude', 'assign']
    dataset: DatasetKind | None
    id_column: str
    label: str
    reason: str = 'Ручная проверка'
    checked_column: str = ''
    reason_editable: bool = True
    column: str = 'Исключить'         # заголовок столбца флажков («Исключено» в журнале исключений)
    fields: tuple[str, ...] = ()
    editable: tuple[str, ...] = ()
    submit: Literal['changed', 'all'] = 'changed'
    journal: str = ''
    target: Literal['groups', 'object-categories', 'well-categories', 'gis-comments', 'wf-status'] = 'groups'


@dataclass
class CellStyle:
    """Оформление ячеек для XLSX (на экране не показывается): заливка и цвет шрифта. ``rows`` — номера строк данных с нуля,
    ``columns`` — ключи колонок; пусто — вся строка. Поздние записи перекрывают ранние."""
    rows: list[int]
    fill: str = ''                    # HEX без «#», например 'FCD5B4'
    font: str = ''
    columns: list[str] = field(default_factory=list)
    border: str = ''                  # 'top' — толстая линия сверху: граница блока (скважины)


@dataclass
class CellMerge:
    """Объединение ячеек для XLSX: строки ``first``..``last`` (с нуля, включительно) по колонкам ``columns`` (подряд).
    Текст — в первой ячейке фрейма, как и остальные значения."""
    first: int
    last: int
    columns: list[str]


@dataclass
class Table:
    id: str
    title: str
    frame: pd.DataFrame
    columns: list[Column] = field(default_factory=list)
    note: str = ''                    # пояснение под таблицей
    collapsed: bool = False           # показывать свёрнутой
    action: TableAction | None = None
    # Строки объединённой шапки над подписями колонок: [(подпись, на сколько колонок), ...]; сумма пролётов — число
    # колонок, пустая подпись — ячейка колонки без группы (в Excel сливается с подписью колонки).
    header: list[list[tuple[str, int]]] = field(default_factory=list)
    # Формулы колонок для Excel (на экране — значения): {ключ колонки: шаблон}. В шаблоне «{ключ}» — ячейка этой колонки
    # в той же строке, «{ключ@prev}» — в предыдущей строке, «{ключ@col}» — весь столбец данных; первая строка данных предыдущей не имеет (формула пуста).
    formulas: dict[str, str] = field(default_factory=dict)
    # Оформление и объединения только для XLSX (заливка по видам пачек, синий шрифт, «не исследовалась»).
    styles: list[CellStyle] = field(default_factory=list)
    merges: list[CellMerge] = field(default_factory=list)

    def __post_init__(self):
        if not self.columns:
            self.columns = [Column(str(c), str(c), kind=_kind_of(self.frame[c])) for c in self.frame.columns]


@dataclass
class Axis:
    label: str
    unit: str = ''
    scale: Literal['value', 'log', 'time', 'category'] = 'value'
    inverse: bool = False
    from_zero: bool = False
    step: float | None = None         # шаг делений (dtick в 5.8)
    categories: list[str] | None = None   # для scale='category': порядок подписей
    minimum: float | None = None      # заданные границы оси (None — автоматически)
    maximum: float | None = None
    color: str = ''                   # цвет подписей и линии оси (правая шкала под один ряд); пусто — цвет по умолчанию
    style: dict[str, Any] = field(default_factory=dict)   # ручное оформление (atlas/chart_style.py): знаки, шрифт, размеры; пусто — авто


@dataclass
class Series:
    name: str
    x: Sequence[Any]
    y: Sequence[Any]
    kind: Literal['points', 'line', 'bar', 'box'] = 'points'   # box: y — [низ, Q1, медиана, Q3, верх] на категорию
    group: str = ''                  # общий цвет и общий пункт легенды
    dashed: bool = False
    dash: Literal['', 'solid', 'dash', 'dot', 'dashdot', 'longdash'] = ''   # пусто — по ``dashed``
    width: float = 0.0               # толщина линии; 0 — по умолчанию
    legend: bool = True
    tooltip: str = ''                # дополнительная строка подсказки
    color: str = ''                  # пусто — цвет по группе из палитры
    symbol: Literal['circle', 'square', 'diamond', 'triangle'] = 'circle'
    hollow: bool = False
    opacity: float = 1.0             # прозрачность маркеров и линии (бледные точки вне порога)
    labels: Sequence[str] | None = None  # строка подсказки на каждую точку (поверх X и Y)
    ids: Sequence[str] | None = None  # идентификаторы точек: по ним щелчок исключает точку
    dataset: DatasetKind | None = None   # набор, к которому относятся ids
    suspect: bool = False            # точки-подсказки выбросов: подсвечены красным; двойной щелчок снимает сомнение
    markers: bool = False            # для 'line': показывать точки на линии (lines+markers в 5.8)
    axis: Literal['y', 'y2', 'y3', 'y4', 'y5'] = 'y'   # правые оси по порядку: y2 — у графика, дальше y3, y4, y5 (смещение и цвет по ряду)
    stack: str = ''                  # одинаковое значение: столбцы или линии с заливкой складываются стопкой
    fill: bool = False               # для 'line': заливка под линией (область); у линии с ``stack`` заливка всегда
    step: bool = False               # для 'line': ступенчатая линия — значение держится до следующей точки
    total: int = 0                   # сколько точек было до прореживания самим модулем (0 — столько, сколько в x)
    # Признаки серии для легенды по рядам: {'Скважина': '№ 101', 'Период': '2023/2024'}. Легенда графика
    # показывает по строке на признак, щелчок по значению скрывает все серии с ним.
    facets: dict[str, str] | None = None
    look: dict[str, Any] | None = None   # ручной вид ряда (atlas/chart_style.py: цвет, линия, маркеры, прозрачность); пусто — как задал модуль
    captions: Sequence[str] | None = None  # текст над каждой точкой на графике (подписи причин без замера); в подсказке — labels
    values: Sequence[float | None] | None = None   # третье значение каждой точки: по нему красятся точки (точки 'points'); None — цвет серии
    values_label: str = ''           # подпись третьего значения для шкалы цвета и подсказки: «Газонасыщенность, д.ед.»
    segments: Sequence[str] | None = None   # подпись внутри каждого сегмента столбца (число скважин); узкий сегмент — выноска или точка, см. ``Chart.callouts``


@dataclass
class Event:
    """Событие на оси времени: вертикальная отметка на графике (ГДИ, смена режима, ремонт)."""
    x: Any                           # дата
    label: str                       # 'Начало закачки 2024'
    kind: Literal['gdi', 'regime', 'repair', 'peak', 'other'] = 'other'
    well: str = ''                   # скважина события; пусто — событие объекта


@dataclass
class Band:
    """Полоса на категорной оси X (годы под столбцами): от категории ``first`` до ``last`` включительно, подпись над графиком."""
    first: int
    last: int
    label: str
    shaded: bool = False             # серая подложка (чередуется с белой)


@dataclass
class Stat:
    """Показатель строки итогов над графиками: «Скважин · 8»."""
    label: str
    value: str
    hint: str = ''                   # пояснение во всплывающей подсказке


@dataclass
class ChartTable:
    """Таблица под графиком: строка на ряд (цвет — цвет ряда), столбец на категорию оси X."""
    rows: list[str]
    columns: list[str]
    cells: list[list[str]]           # cells[строка][столбец]
    colors: list[str] = field(default_factory=list)   # цвет подписи строки; пусто — цвет ряда с тем же номером
    aligned: bool = False            # столбцы (кроме двух первых: подпись строки и «Фонд») стоят точно под столбиками графика; график уступает слева место под подписи
    swatches: bool = True            # цветной маркер у строк: строки таблицы — ряды графика; False — строки сами по себе (группы)


@dataclass
class HeatMap:
    """Тепловая карта «строка × столбец» вместо рядов: цветная таблица с числами в ячейках. Нет данных — штриховка."""
    rows: list[str]
    columns: list[str]
    values: list[list[float | None]]   # values[строка][столбец]; None — нет данных
    texts: list[list[str]]             # подпись ячейки: «19», «48 %»; у ячейки без данных — причина («нет фонда»), пусто — ``missing_text``
    unit: str = ''                     # подпись шкалы цвета: «Скважин», «% от фонда ГСП»
    maximum: float | None = None       # верх шкалы цвета; None — максимум значений
    missing_text: str = 'нет данных'


@dataclass
class WellStrips:
    """Скважины × сезоны: строка — скважина, квадрат — сезон (есть в перечне / нет / ревизии не было). Цвет квадрата — цвет ГСП."""
    rows: list[str]                    # «№ 38»
    groups: list[str]                  # ГСП каждой строки
    columns: list[str]                 # сезоны
    cells: list[list[int | None]]      # 1 — скважина в перечне сезона, 0 — нет, None — по ГСП в сезоне ревизии не было
    counts: list[int]                  # в скольких сезонах скважина встретилась
    layout: Literal['matrix', 'panels'] = 'matrix'   # matrix — один список; panels — отдельная колонка на каждую ГСП
    missing_text: str = 'нет ревизии'
    colors: dict[str, str] = field(default_factory=dict)   # цвет каждой ГСП (сквозная палитра групп)


@dataclass
class Figure:
    """Рисунок вместо рядов: схема скважины или планшет ГИС по глубине (фигуры считает модуль, рисует общий компонент WellFigure)."""
    kind: Literal['construction', 'planshet']
    data: dict[str, Any]


@dataclass
class Chart:
    id: str
    title: str
    x: Axis
    y: Axis
    series: list[Series] = field(default_factory=list)
    crosshair: bool = False
    y2: Axis | None = None           # вторая шкала справа (две шкалы Y)
    y3: Axis | None = None           # третья шкала: вторая справа, снаружи от y2 (требует y2)
    y4: Axis | None = None           # четвёртая шкала справа, снаружи от y3 (требует y3)
    y5: Axis | None = None           # пятая шкала справа, снаружи от y4 (требует y4)
    style: dict[str, Any] = field(default_factory=dict)   # ручное оформление графика (atlas/chart_style.py): заголовок, легенда, сетка, фон
    events: list[Event] = field(default_factory=list)   # отметки: дата на оси времени, число на числовой оси (накопленный объём)
    callouts: Literal['box', 'dot'] = 'box'   # узкие сегменты столбцов с ``Series.segments``: 'box' — выноска в рамке цвета ряда, 'dot' — точка (числа в ``table``)
    table: ChartTable | None = None  # таблица под графиком (экран и экспорт)
    bands: list[Band] = field(default_factory=list)   # полосы по категориям оси X с подписью (годы)
    heat: HeatMap | None = None      # тепловая карта вместо рядов (series пуст)
    strips: WellStrips | None = None  # скважины × сезоны вместо рядов (series пуст)
    figure: Figure | None = None     # схема скважины или планшет ГИС вместо рядов (series пуст); скачивание — кнопками на самом рисунке

    def right_axes(self) -> list[tuple[str, Axis]]:
        """Правые шкалы по порядку от графика наружу: [('y2', ...), ('y3', ...), ...]; идут подряд, без пропусков."""
        out = []
        for name in ('y2', 'y3', 'y4', 'y5'):
            axis = getattr(self, name)
            if axis is None:
                break
            out.append((name, axis))
        return out

    def axis_names(self) -> list[str]:
        """Имена всех шкал Y по порядку: 'y' и правые шкалы."""
        return ['y'] + [name for name, _ in self.right_axes()]

    def axis_at(self, name: str) -> Axis:
        """Шкала по имени; неизвестное или отсутствующее имя — основная шкала 'y'."""
        if name == 'y':
            return self.y
        return dict(self.right_axes()).get(name, self.y)


@dataclass
class Note:
    text: str
    level: Literal['info', 'warning'] = 'info'


@dataclass
class Command:
    """Кнопка под результатом: POST на адрес API проекта, затем проект обновляется и модуль пересчитывается.

    ``path`` — относительно ``/api/projects/{проект}/`` (например ``'exclusions/state'``), ``body`` — тело запроса.
    """
    label: str
    path: str
    body: dict[str, Any] = field(default_factory=dict)
    confirm: str = ''                 # вопрос перед выполнением; пусто — без вопроса
    done: str = ''                    # сообщение после успеха
    primary: bool = False


@dataclass
class Result:
    tables: list[Table] = field(default_factory=list)
    charts: list[Chart] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)
    commands: list[Command] = field(default_factory=list)
    summary: list[Stat] = field(default_factory=list)     # строка итогов над графиками

    def to_json(self, thin: bool = True, defer: bool = True) -> dict[str, Any]:
        """JSON для интерфейса. ``thin`` — экранное прореживание линий (atlas.thinning), большие таблицы — по запросу;
        сам ``Result`` не меняется: выгрузки берут из него все точки."""
        return {
            'tables': [_table_json(t, defer=defer) for t in self.tables],
            'charts': [_chart_json(c, thin) for c in self.charts],
            'notes': [asdict(n) for n in self.notes],
            'commands': [asdict(c) for c in self.commands],
            'summary': [asdict(st) for st in self.summary],
        }


class Data(Mapping):
    """Данные проекта для модуля: ``data[kind]`` — с применёнными исключениями,
    ``data.raw[kind]`` — исходные (с ``_point_id``), ``data.excluded`` — журнал исключений."""

    def __init__(self, frames: Mapping[DatasetKind, pd.DataFrame], raw: Mapping[DatasetKind, pd.DataFrame] | None = None,
                 excluded: Mapping[str, dict] | None = None):
        self._frames = dict(frames)
        self.raw = dict(raw if raw is not None else frames)
        self.excluded = dict(excluded or {})
        self.settings: dict[str, Any] = {}
        self.revision: int | None = None
        self.mapping: dict[str, dict[str, str]] = {}    # скважина -> {'group': ..., 'subgroup': ...}
        # Сведения о проекте (atlas.projects.ProjectInfo): name, demo, tables, history(), catalog(). Задаёт ядро.
        self.project: Any = None
        self.model_notes: list[str] = []                 # заметки о выбранных моделях tNav, которые не прочитались
        self.wells: list[str] = []                       # все скважины проекта (по всем наборам), по номеру

    def __getitem__(self, kind):
        return self._frames[kind]

    def __iter__(self):
        return iter(self._frames)

    def __len__(self):
        return len(self._frames)


class Module:
    """Базовый класс. Подкласс задаёт ``spec`` и реализует ``run``; без состояния."""
    spec: ClassVar[ModuleSpec]

    def run(self, data: Data, params: dict[str, Any]) -> Result:
        raise NotImplementedError

    # Сохранённые параметры просмотра (settings.panels[id]) и записи «Расчет …» в журнале.
    # По умолчанию хранятся сами параметры; модуль может хранить их в формате 5.8 для совместимости.
    history_action: ClassVar[str] = ''

    def options(self, name: str, data: Data, params: dict[str, Any]) -> list[str]:
        """Варианты для параметра с ``dynamic=True``; ``params`` — текущие значения остальных параметров."""
        if name == BUILDER_LAYOUTS:
            from .builder_library import layout_names
            return layout_names(data)
        raise KeyError(f'У модуля {self.spec.id} нет списка {name}')

    def catalog(self, data: Data) -> dict[str, Any]:
        """Справочник раздела по данным проекта (``POST /api/modules/{id}/catalog``): например, поля для конструктора графиков."""
        raise KeyError(f'У модуля {self.spec.id} нет справочника')

    def panel_key(self, panel: int = 0) -> str:
        """Ключ сохранённого вида в settings.panels. Для нескольких панелей — свой на каждую."""
        return self.spec.id

    def panel_fallbacks(self, panel: int = 0) -> tuple[str, ...]:
        """Прежние ключи того же вида (сохранённые старыми версиями)."""
        return ()

    def save_state(self, params: dict[str, Any], data: Data) -> dict[str, Any]:
        return dict(params)

    def load_state(self, state: Mapping[str, Any]) -> dict[str, Any]:
        names = {p.name for p in self.spec.params}
        return {k: v for k, v in state.items() if k in names}


class MissingData(LookupError):
    def __init__(self, kinds: Sequence[DatasetKind]):
        self.kinds = list(kinds)
        names = ', '.join(f'«{k.label}»' for k in self.kinds)
        super().__init__(f'В проекте нет данных: {names}. Загрузите их в разделе импорта.')


# ---------- сериализация ----------

def _kind_of(series: pd.Series) -> str:
    if pd.api.types.is_datetime64_any_dtype(series):
        return 'date'
    if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
        return 'number'
    return 'text'


def plain(value: Any) -> Any:
    """Значение для JSON: NaN/NaT -> None, даты -> ISO, numpy -> python."""
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, dt.datetime):          # pd.Timestamp тоже datetime
        midnight = (value.hour, value.minute, value.second, value.microsecond) == (0, 0, 0, 0)
        return value.date().isoformat() if midnight else value.isoformat()
    if isinstance(value, np.datetime64):
        return plain(pd.Timestamp(value))
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _column(values: Any) -> list[Any]:
    if isinstance(values, (pd.Series, pd.Index)):
        values = values.to_numpy() if not pd.api.types.is_datetime64_any_dtype(values) else pd.DatetimeIndex(values)
    if isinstance(values, np.ndarray) and values.dtype.kind == 'M':
        values = pd.DatetimeIndex(values)        # ndarray.tolist() отдал бы наносекунды целыми числами
    return [plain(v) for v in (values.tolist() if hasattr(values, 'tolist') else list(values))]


DEFER_ROWS = 20000     # свёрнутая таблица без действий больше этого не отправляется, пока её не раскроют


def is_deferred(t: Table) -> bool:
    return t.collapsed and t.action is None and len(t.frame) > DEFER_ROWS


def _table_json(t: Table, defer: bool = False) -> dict[str, Any]:
    keys = [c.key for c in t.columns]
    if defer and is_deferred(t):
        return {'id': t.id, 'title': t.title, 'columns': [asdict(c) for c in t.columns], 'note': t.note,
                'collapsed': t.collapsed, 'action': None, 'rows': [[] for _ in keys], 'count': len(t.frame),
                'deferred': True}
    extra = [k for k in (t.action.id_column, t.action.checked_column) if k and k not in keys] if t.action else []
    frame = t.frame[keys + extra]
    action = None
    if t.action:
        action = {**asdict(t.action), 'dataset': t.action.dataset.value if t.action.dataset else None,
                  'values': {k: _column(t.frame[k]) for k in t.action.fields},
                  'ids': _column(frame[t.action.id_column]),
                  'checked': [bool(v) for v in frame[t.action.checked_column]] if t.action.checked_column else None}
    out = {'id': t.id, 'title': t.title, 'columns': [asdict(c) for c in t.columns], 'note': t.note,
           'collapsed': t.collapsed, 'action': action, 'header': [[[a, n] for a, n in row] for row in t.header],
           'rows': [_column(frame[k]) for k in keys], 'count': len(frame)}  # по колонкам: компактнее
    if t.styles:      # оформление ячеек, как в XLSX (заливка, шрифт, линия) — на экране то же самое
        out['styles'] = [{'rows': s.rows, 'fill': s.fill, 'font': s.font, 'columns': s.columns, 'border': s.border}
                         for s in t.styles]
    if t.merges:      # объединения ячеек, как в XLSX
        out['merges'] = [{'first': m.first, 'last': m.last, 'columns': m.columns} for m in t.merges]
    return out


def _series_json(s: Series, keep: Any = None) -> dict[str, Any]:
    """``keep`` — индексы точек, которые уходят на экран (None — все). ``total`` — сколько точек в серии на самом деле."""
    out = {f.name: getattr(s, f.name) for f in fields(s) if f.name not in ('x', 'y', 'ids', 'dataset', 'labels', 'values')}
    full = len(s.x)
    out['total'] = max(s.total, full)

    def take(values):
        if values is None:
            return None
        if keep is None:
            return list(values)
        return [values[i] for i in keep] if not isinstance(values, (np.ndarray, pd.Series, pd.Index)) \
            else (values.iloc[keep] if isinstance(values, pd.Series) else values[keep])
    out.update(x=_column(take(s.x)), y=_column(take(s.y)),
               ids=None if s.ids is None else [str(v) for v in take(s.ids)],
               labels=None if s.labels is None else [str(v) for v in take(s.labels)],
               values=None if s.values is None else _column(take(s.values)),
               dataset=s.dataset.value if s.dataset else None)
    return out


def _event_x(x: Any) -> Any:
    """Положение события: дата для оси времени, число (накопленный объём) для числовой оси."""
    if x is None:
        return None
    if isinstance(x, (int, float, np.number)):
        return plain(float(x))
    return plain(pd.Timestamp(x))


def _chart_json(c: Chart, thin: bool = True) -> dict[str, Any]:
    from . import thinning
    kept = thinning.screen_indices(c) if thin else {}
    return {'id': c.id, 'title': c.title, 'x': asdict(c.x), 'y': asdict(c.y), 'crosshair': c.crosshair, 'style': c.style,
            'y2': asdict(c.y2) if c.y2 else None, 'y3': asdict(c.y3) if c.y3 else None,
            'y4': asdict(c.y4) if c.y4 else None, 'y5': asdict(c.y5) if c.y5 else None,
            'series': [_series_json(s, kept.get(i)) for i, s in enumerate(c.series)],
            'events': [{'x': _event_x(e.x), 'label': e.label, 'kind': e.kind,
                        'well': e.well} for e in c.events],
            'bands': [asdict(b) for b in c.bands],
            'callouts': c.callouts, 'table': asdict(c.table) if c.table else None, 'heat': asdict(c.heat) if c.heat else None,
            'strips': asdict(c.strips) if c.strips else None, 'figure': asdict(c.figure) if c.figure else None}
