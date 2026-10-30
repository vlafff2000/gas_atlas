"""Чек-лист «Импорт данных»: все виды данных, которые можно загрузить в проект, что уже загружено (строк) и в каком виде нужен файл.

Только справка и счётчики: данные не читаются и не меняются. Состав проекта берётся из ``manifest['tables']`` (строк в таблице)
и ``manifest['groups']``. Формат: колонки и пример строки берутся из шаблонов ``input_templates``, где шаблон есть,
для остальных видов описаны здесь (разбор — в ``atlas/engine/core/*_import.py``)."""
from __future__ import annotations

import io
from typing import Any

import pandas as pd

from openpyxl import load_workbook

from atlas.engine.core.templates import input_templates

# (ключ таблицы проекта, название, где нужно, шаблон или пример для скачивания, колонки, пример строки, пояснение)
ITEMS: list[dict[str, Any]] = [
    {'key': 'production', 'label': 'Расходы (динамика по скважинам)', 'used': 'Производительность, сезонные показатели, графики, сводки по группам',
     'template': 'Шаблон_динамики.xlsx', 'note': 'Одна строка — скважина и сутки. Можно длинной таблицей, матрицей «даты × скважины» или листами «Отборы» / «Закачка» из Базы ПХГ.'},
    {'key': 'operations', 'label': 'Суточная эксплуатация (часы, объёмы, давления)', 'used': 'Эксплуатация скважин, простои, расход в часы работы',
     'template': 'Шаблон_суточной_эксплуатации.xlsx', 'note': 'Часы 0–24; пустые часы неизвестны и не заменяются на 24.'},
    {'key': 'gdi', 'label': 'ГДИ', 'used': 'Газодинамические исследования, коэффициенты a и b, АФ скважин',
     'template': 'Шаблон_ГДИ.xlsx', 'example': '06_GDI_5_columns.csv', 'note': 'Для «надёжного» исследования нужно не менее трёх режимов с разными положительными Q.'},
    {'key': 'response', 'label': 'Реагирование (уровни и приведённое давление)', 'used': 'Графики реагирования',
     'template': 'Шаблон_реагирования.xlsx', 'example': '07_response.csv', 'note': 'Допустим уровень, давление или оба показателя; пустые значения не заменять нулём.'},
    {'key': 'object_pressure', 'label': 'Давление объекта', 'used': 'Давление объекта, спад давления',
     'template': 'Шаблон_давления_объекта.xlsx', 'note': 'Две колонки: дата и пластовое давление (абсолютное).'},
    {'key': 'pressure_match', 'label': 'Давления: факт и модели (кроссплот)', 'used': 'Кроссплот давлений, сравнение факта и моделей',
     'columns': ['Лист «Факт»: Дата, Скважина, Давление', 'Листы «Модель 1», «Модель 2»…: те же колонки', 'Лист «Фонд» (необязательно): скважина, период'],
     'note': 'Одна книга на объект. Листы определяются сами; роли листов и сценарии можно уточнить на вкладке давлений.'},
    {'key': 'water', 'label': 'Вода: контроль и замеры по месяцам', 'used': 'Вынос воды и водный фактор',
     'template': 'Шаблон_контроля_воды.xlsx', 'note': 'Также принимаются месячные файлы замеров воды в старом формате Карт ГСП (скважина, водный фактор).'},
    {'key': 'water_factor', 'label': 'Вынос воды по объекту', 'used': 'Вынос воды и водный фактор по объекту',
     'columns': ['Дата', 'Газ в пласте / суточный объём', 'Вода, м³'], 'note': 'Суточные значения по объекту; удобнее взять из «БД по учету газа» Базы ПХГ.'},
    {'key': 'plan', 'label': 'План по группам', 'used': 'Сезонные показатели по группам, план/факт',
     'template': 'Шаблон_плана.xlsx', 'note': 'Группа, месяц, режим (отбор/закачка), план в млн м³.'},
    {'key': 'groups', 'label': 'Группы и подгруппы скважин', 'used': 'Все разделы с группами (ГСП, СП), карты, отчёты',
     'template': 'Шаблон_групп.xlsx', 'note': 'Названия групп нормируются единой схемой: «ГСП-1» и «ГСП 1» — одна группа.'},
    {'key': 'bottom', 'label': 'Замеры забоя', 'used': 'Состояние скважин, авторский надзор',
     'template': 'Шаблон_замеров_забоя.xlsx'},
    {'key': 'construction', 'label': 'Конструкция скважин', 'used': 'Паспорт скважины, авторский надзор',
     'template': 'Шаблон_конструкции.xlsx'},
    {'key': 'well_geo', 'label': 'Положение, альтитуды и перфорация скважин', 'used': 'Карты, ГИС и ГВК, базовая модель',
     'columns': ['Скважина', 'X', 'Y', 'Альтитуда', 'Перфорация верх', 'Перфорация низ'],
     'note': 'Принимаются таблица Excel/CSV, текстовые файлы «скважина X Y» и выгрузка траекторий. Достаточно координат, альтитуд или перфорации.'},
    {'key': 'elpro', 'label': 'ЭЛПРО (параметры работы ГСП)', 'used': 'Сравнение с ЭЛПРО, режимы групп',
     'columns': ['Дата', 'Режим', 'ГСП', 'Скважина', 'Y круг…', 'Q газа, тыс. м³/сут'],
     'note': 'Готовая «БД_ЭЛПРО» из Базы ПХГ (лист «Данные») или месячные файлы «Параметры работы ГСП».'},
    {'key': 'gas_db', 'label': 'БД по учету газа (суточный объём по объекту)', 'used': 'Нормировка на узел учёта, вынос воды по объекту',
     'columns': ['Режим', 'Дата', 'Год', 'Месяц', 'Сезон', 'Файл', 'Лист', 'Отбор из ПХГ, тыс. м³/сут', 'Закачка в ПХГ, тыс. м³/сут'],
     'note': 'Выходной файл Базы ПХГ, лист «БД».'},
    {'key': 'ggh', 'label': 'Газогидрохимия (ГГХ)', 'used': 'Раздел ГГХ, отчёт Word по ГГХ',
     'example': '08_GGH.xlsx', 'columns': ['№№ скв.', 'Дата отбора', 'Водоносный горизонт', 'Газонасыщенность, см³/л', 'СН4', 'С2Н6', '…'],
     'note': 'Лист «Общий» книги отчёта по ГГХ; шапка ищется в первых 20 строках.'},
    {'key': 'krs_works', 'label': 'КРС: проведённые капитальные ремонты', 'used': 'Паспорт скважины, КРС: приоритет ремонта',
     'columns': ['Скважина', 'Год', 'Тип ремонта', '…'], 'example': ['31', '2023', 'Колтюбинг без СКО'],
     'note': 'Лист «Ремонты» книги «КРС_для_Атласа.xlsx» из «Работы с исходными данными» → «Состояние скважин и приоритет КР». '
             'Книга загружается целиком (ремонты и приоритет) во вкладке «Импорт».'},
    {'key': 'krs_priority', 'label': 'КРС: приоритет капремонта по скважинам', 'used': 'Паспорт скважины, КРС: приоритет ремонта',
     'columns': ['Скважина', 'ГСП', 'Приоритет итог', 'Приоритет (расчёт)', 'Приоритет вручную', 'Песок в ревизиях КРУ', 'Причина'],
     'note': 'Лист «Приоритет» той же книги. Приоритет (1 — срочно) — подсказка, ручное значение главнее расчёта: решает инженер.'},
    {'key': 'gis_packs', 'label': 'ГИС: пачки', 'used': 'ГИС и ГВК, hэф, Кг, уровень ГВК',
     'columns': ['Скважина', 'Дата', 'Пачка', 'hг эф, м', 'Кг ср.взв', 'ГВК а.о., м'], 'note': 'Лист «Свод» книги «ГИС_свод.xlsx» Базы ПХГ или CSV gis_packs.'},
    {'key': 'gis_intervals', 'label': 'ГИС: интервалы', 'used': 'ГИС и ГВК, кривые и столбцы, Σ hi·Кг',
     'columns': ['Скважина', 'Дата', 'Пачка', 'От, м', 'До, м', 'Кг'], 'note': 'Лист «Интервалы» книги «ГИС_свод.xlsx» или CSV gis_intervals.'},
    {'key': 'gis_observations', 'label': 'ГИС: замеры (статус по скважине и дате)', 'used': 'ГИС и ГВК, покрытие замерами',
     'columns': ['Скважина', 'Дата', 'Статус', 'Пачек'], 'note': 'Лист «Замеры» книги «ГИС_свод.xlsx» или CSV gis_observations.'},
]


def _template_format(name: str) -> tuple[list[str], list[str]]:
    """Колонки и пример строки первого листа шаблона."""
    book = input_templates().get(name)
    if not book:
        return [], []
    sheet = load_workbook(io.BytesIO(book), read_only=True).worksheets[0]
    rows = list(sheet.iter_rows(min_row=1, max_row=2, values_only=True))
    cell = lambda v: '' if v is None else (v.strftime('%d.%m.%Y') if hasattr(v, 'strftime') else str(v))
    return [cell(v) for v in rows[0]], ([cell(v) for v in rows[1]] if len(rows) > 1 else [])


KINDS = {'injection': 'закачка', 'withdrawal': 'отбор'}


def _has(f: pd.DataFrame, *cols: str) -> bool:
    return all(c in f.columns for c in cols)


def _n(f: pd.DataFrame, col: str) -> int:
    return int(f[col].dropna().astype(str).str.strip().replace('', pd.NA).dropna().nunique()) if _has(f, col) else 0


def _period(f: pd.DataFrame, col: str = 'date') -> str:
    if not _has(f, col):
        return ''
    d = pd.to_datetime(f[col], errors='coerce').dropna()
    return f'{d.min():%d.%m.%Y} — {d.max():%d.%m.%Y}' if len(d) else ''


def _list(f: pd.DataFrame, col: str, limit: int = 12, counts: bool = False) -> str:
    if not _has(f, col):
        return ''
    vc = f[col].dropna().astype(str).str.strip()
    vc = vc[~vc.isin(['', 'nan', 'None'])].value_counts()
    if not len(vc):
        return ''
    names = sorted(vc.index, key=lambda x: x)
    shown = ', '.join(f'{x} ({int(vc[x]):,})'.replace(',', ' ') if counts else x for x in names[:limit])
    return shown + (f' и ещё {len(names) - limit}' if len(names) > limit else '')


def _filled(f: pd.DataFrame, col: str) -> int:
    """Скважин, у которых колонка заполнена."""
    if not _has(f, 'well', col):
        return 0
    return int(f.loc[pd.to_numeric(f[col], errors='coerce').notna(), 'well'].nunique())


def _lines(key: str, f: pd.DataFrame) -> list[list[str]]:
    """Содержание таблицы: пары «показатель — значение». Первая пара — краткая сводка для строки чек-листа."""
    out: list[list[str]] = []

    def add(label: str, value: Any) -> None:
        if value not in ('', None, 0):
            out.append([label, str(value)])

    add('Скважин', _n(f, 'well'))
    add('Период', _period(f))
    if key == 'production':
        add('Сезоны', _list(f, 'season', 30, counts=True))
        add('Режимы', _list(f.assign(kind=f['kind'].map(KINDS).fillna(f['kind'])) if _has(f, 'kind') else f, 'kind', counts=True))
        add('Групп', _n(f, 'group'))
    elif key == 'operations':
        add('Типы', _list(f.assign(kind=f['kind'].map(KINDS).fillna(f['kind'])) if _has(f, 'kind') else f, 'kind', counts=True))
    elif key == 'gdi':
        add('Исследований', int(f.drop_duplicates([c for c in ('well', 'date', 'method', 'study') if c in f.columns]).shape[0]))
        add('Методы', _list(f, 'method', counts=True))
        add('Сезоны', _list(f, 'season', 30))
    elif key == 'response':
        add('Горизонты', _list(f, 'horizon'))
        add('Скважин с уровнем', _filled(f, 'level'))
        add('Скважин с давлением', _filled(f, 'pressure'))
    elif key == 'pressure_match':
        add('Объекты', _list(f, 'object'))
        add('Сценарии', _list(f, 'scenario'))
        add('Скважин с фактом', _filled(f, 'fact'))
        add('Скважин с моделью', _filled(f, 'model'))
    elif key == 'water':
        add('Скважин с водным фактором', _filled(f, 'water_factor_l'))
    elif key == 'plan':
        add('Группы', _list(f, 'group'))
    elif key == 'well_geo':
        add('Скважин с координатами X, Y', int(f.loc[pd.to_numeric(f.get('x'), errors='coerce').notna() & pd.to_numeric(f.get('y'), errors='coerce').notna(), 'well'].nunique()) if _has(f, 'x', 'y') else 0)
        add('Скважин с альтитудой', _filled(f, 'altitude'))
        add('Скважин с перфорацией', int(f.loc[pd.to_numeric(f.get('perf_top'), errors='coerce').notna() & pd.to_numeric(f.get('perf_bottom'), errors='coerce').notna(), 'well'].nunique()) if _has(f, 'perf_top', 'perf_bottom') else 0)
    elif key == 'elpro':
        add('Групп', _n(f, 'group'))
    elif key == 'gas_db':
        add('Суток отбора', int((f.get('kind') == 'withdrawal').sum()) if _has(f, 'kind') else 0)
        add('Суток закачки', int((f.get('kind') == 'injection').sum()) if _has(f, 'kind') else 0)
        add('Суток с выносом воды', int(pd.to_numeric(f.get('water'), errors='coerce').notna().sum()) if _has(f, 'water') else 0)
    elif key == 'ggh':
        add('Горизонты', _list(f, 'horizon'))
        add('Замеров с газонасыщенностью', int(pd.to_numeric(f.get('gas'), errors='coerce').notna().sum()) if _has(f, 'gas') else 0)
    elif key == 'gis_packs':
        add('Сезоны', _list(f, 'season', 30))
        add('Пачки', _list(f, 'pack'))
        add('Скважин с уровнем ГВК', _filled(f, 'gvk_abs_m'))
    elif key == 'krs_works':
        add('Типы ремонта', _list(f, 'work_type', counts=True))
        add('Годы', _list(f.assign(year=pd.to_numeric(f['year'], errors='coerce').dropna().astype(int)) if _has(f, 'year') else f, 'year', 30))
    elif key == 'krs_priority':
        add('С приоритетом', int(pd.to_numeric(f.get('priority'), errors='coerce').notna().sum()) if _has(f, 'priority') else 0)
        add('Приоритет 1 (срочно)', int(pd.to_numeric(f.get('priority'), errors='coerce').eq(1).sum()) if _has(f, 'priority') else 0)
    elif key == 'gis_intervals':
        add('Интервалов', len(f))
    elif key == 'gis_observations':
        add('Статусы', _list(f, 'status', counts=True))
    add('Строк', f'{len(f):,}'.replace(',', ' '))
    return out


def build(manifest: dict[str, Any], frames: dict[str, pd.DataFrame] | None = None) -> list[dict[str, Any]]:
    tables = manifest.get('tables', {})
    groups = manifest.get('groups', {})
    frames = frames or {}
    out = []
    for item in ITEMS:
        columns, example = _template_format(item['template']) if item.get('template') else (item.get('columns', []), [])
        key = item['key']
        count = len(groups) if key == 'groups' else int(tables.get(key, 0) or 0)
        frame = frames.get(key)
        if key == 'groups' and groups:
            lines = [['Скважин с группой', str(len(groups))]]
            names = pd.Series([v.get('group') if isinstance(v, dict) else v for v in groups.values()]).dropna().astype(str)
            if len(names):
                vc = names.value_counts()
                lines.append(['Группы (скважин)', ', '.join(f'{k} ({int(vc[k])})' for k in sorted(vc.index)[:30])])
        else:
            lines = _lines(key, frame) if frame is not None and len(frame) else []
        out.append({'key': key, 'label': item['label'], 'used': item['used'], 'count': count,
                    'unit': 'скважин' if key == 'groups' else 'строк', 'summary': ' · '.join(f'{k.lower()} {v}' for k, v in lines[:2]),
                    'details': lines, 'columns': columns, 'example': example, 'note': item.get('note', ''),
                    'template': item.get('template'), 'example_file': item.get('example')})
    return out
