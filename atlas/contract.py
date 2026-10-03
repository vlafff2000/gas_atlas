"""Контракт модуля Gas Atlas 6.

Модуль — класс с декларативным ``spec`` и чистым методом ``run(data, params) -> Result``.
Интерфейс не импортирует модули: он читает ``GET /api/modules`` и строит панель параметров
и вывод обобщённо. Всё, что модуль хочет показать, выражается типами из этого файла.
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import asdict, dataclass, field, fields
from typing import Any, ClassVar, Literal, Mapping, Sequence

import numpy as np
import pandas as pd

from .domain import DatasetKind

ParamKind = Literal['number', 'integer', 'boolean', 'choice', 'multi', 'date', 'text']


class ParamError(ValueError):
    """Неверное значение параметра; текст показывается пользователю как есть."""


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
    empty: str = 'все'                # что значит пустой выбор в списке: 'все' или 'ничего'
    show_if: dict[str, Any] | None = None   # показывать, только если параметры равны этим значениям

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
                return pd.Timestamp(str(value)).strftime('%Y-%m-%d')
            except (TypeError, ValueError):
                raise ParamError(f'«{self.label}»: ожидается дата ГГГГ-ММ-ДД') from None
        if self.kind == 'text':
            return str(value)[:5000]
        if self.kind == 'choice':
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
        raise ParamError(f'Неизвестный тип параметра {self.kind}')


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
    или ``object-categories`` (категории объектов кроссплота; ``id_column`` — объект, поле ``category``).
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
    target: Literal['groups', 'object-categories'] = 'groups'


@dataclass
class Table:
    id: str
    title: str
    frame: pd.DataFrame
    columns: list[Column] = field(default_factory=list)
    note: str = ''                    # пояснение под таблицей
    collapsed: bool = False           # показывать свёрнутой
    action: TableAction | None = None

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
    labels: Sequence[str] | None = None  # строка подсказки на каждую точку (поверх X и Y)
    ids: Sequence[str] | None = None  # идентификаторы точек: по ним щелчок исключает точку
    dataset: DatasetKind | None = None   # набор, к которому относятся ids
    markers: bool = False            # для 'line': показывать точки на линии (lines+markers в 5.8)
    axis: Literal['y', 'y2'] = 'y'   # 'y2' — правая ось Chart.y2


@dataclass
class Chart:
    id: str
    title: str
    x: Axis
    y: Axis
    series: list[Series] = field(default_factory=list)
    crosshair: bool = False
    y2: Axis | None = None           # вторая шкала справа (две шкалы Y)


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

    def to_json(self) -> dict[str, Any]:
        return {
            'tables': [_table_json(t) for t in self.tables],
            'charts': [_chart_json(c) for c in self.charts],
            'notes': [asdict(n) for n in self.notes],
            'commands': [asdict(c) for c in self.commands],
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
        raise KeyError(f'У модуля {self.spec.id} нет списка {name}')

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


def _table_json(t: Table) -> dict[str, Any]:
    keys = [c.key for c in t.columns]
    extra = [k for k in (t.action.id_column, t.action.checked_column) if k and k not in keys] if t.action else []
    frame = t.frame[keys + extra]
    action = None
    if t.action:
        action = {**asdict(t.action), 'dataset': t.action.dataset.value if t.action.dataset else None,
                  'values': {k: _column(t.frame[k]) for k in t.action.fields},
                  'ids': _column(frame[t.action.id_column]),
                  'checked': [bool(v) for v in frame[t.action.checked_column]] if t.action.checked_column else None}
    return {'id': t.id, 'title': t.title, 'columns': [asdict(c) for c in t.columns], 'note': t.note,
            'collapsed': t.collapsed, 'action': action,
            'rows': [_column(frame[k]) for k in keys], 'count': len(frame)}  # по колонкам: компактнее


def _series_json(s: Series) -> dict[str, Any]:
    out = {f.name: getattr(s, f.name) for f in fields(s) if f.name not in ('x', 'y', 'ids', 'dataset', 'labels')}
    out.update(x=_column(s.x), y=_column(s.y), ids=None if s.ids is None else [str(v) for v in s.ids],
               labels=None if s.labels is None else [str(v) for v in s.labels],
               dataset=s.dataset.value if s.dataset else None)
    return out


def _chart_json(c: Chart) -> dict[str, Any]:
    return {'id': c.id, 'title': c.title, 'x': asdict(c.x), 'y': asdict(c.y), 'crosshair': c.crosshair,
            'y2': asdict(c.y2) if c.y2 else None,
            'series': [_series_json(s) for s in c.series]}
