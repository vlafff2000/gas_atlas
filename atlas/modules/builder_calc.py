"""Конструктор графиков, этап 4: преобразования ряда и калькулятор формул.

Преобразование (``row.transform``) меняет значения Y одного ряда по каждой кривой (скважине) отдельно: накопленное, скользящее
среднее, сводка по суткам / месяцам / скважинам группы, нормировка, умножение / деление / сложение с числом, разность соседних.
Это представление уже выбранных данных, а не расчёт ядра: формулы — сумма, среднее, деление, как в Excel.

Формула (``row.source == 'formula'``) — ряд из других рядов макета по буквам (A — ряд 1, B — ряд 2 …, либо R1, R2 …),
чисел, операций ``+ − × ÷ ^``, скобок и функций из белого списка. Разбор свой (рекурсивный спуск), ``eval`` не используется:
имя вне списка, атрибут, вызов чего-то другого — ошибка разбора. Деление на ноль, логарифм и корень от недопустимого числа —
пропуск точки и заметка со счётчиком.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping

import numpy as np
import pandas as pd

from atlas.engine.core.loader import group_key

from ..contract import Note, ParamError

# ---------- преобразования ----------

TRANSFORMS = {
    'none': 'без преобразования', 'cumsum': 'накопленное', 'rolling': 'скользящее среднее',
    'day': 'по суткам', 'month': 'по месяцам', 'group': 'по скважинам (вся выборка)',
    'norm': 'нормировка', 'mul': 'умножить на число', 'div': 'разделить на число', 'add': 'прибавить число',
    'diff': 'разность соседних значений',
}
AGGS = {'mean': 'среднее', 'sum': 'сумма', 'max': 'максимум', 'min': 'минимум'}
NORMS = {'first': 'на первую точку', 'max': 'на максимум', 'value': 'на число'}
ROLL_BY = {'points': 'точек', 'days': 'суток'}
MAX_WINDOW = 10_000
KEEP_IDS = ('none', 'mul', 'div', 'add', 'norm')      # точка ряда = строка набора: её можно исключить щелчком
# Накопленное и сумма за месяц: единица суточного значения → единица объёма и множитель (сумма суточных = объём за период).
CUMULATIVE = {'тыс. м³/сут': ('млн м³', 1 / 1000), 'млн м³/сут': ('млрд м³', 1 / 1000), 'м³/сут': ('м³', 1.0),
              'м³': ('тыс. м³', 1 / 1000), 'тыс. м³': ('млн м³', 1 / 1000), 'млн м³': ('млн м³', 1.0), 'ч': ('ч', 1.0)}
# Перевод единиц умножением или делением на число: (единица, множитель) → новая единица.
LADDERS = (('м³', 'тыс. м³', 'млн м³', 'млрд м³'), ('м³/сут', 'тыс. м³/сут', 'млн м³/сут', 'млрд м³/сут'))
PRESSURE = (('кгс/см²', 'МПа', 0.0980665), ('кгс/см²', 'атм', 0.967841), ('кгс/см²', 'бар', 0.980665))


@dataclass(frozen=True)
class Transform:
    op: str = 'none'
    n: int = 7
    by: str = 'points'          # скользящее: окно в точках или в сутках
    agg: str = 'mean'           # сутки, месяцы, группа
    norm: str = 'first'
    value: float = 1.0
    overlay: bool = False       # сезоны накладываются: X — сутки от начала сезона, каждый сезон — отдельная кривая
    season: bool = False        # накопленное заново с начала каждого сезона (границы — период расхода в данных проекта)
    cum: bool = False           # после суммы по скважинам / суткам / месяцам — ещё и накопленное (нарастающий итог по объекту)


def _num(value: Any, what: str) -> float:
    try:
        number = float(str(value).replace(',', '.').replace(' ', '').replace(' ', ''))
    except (TypeError, ValueError):
        raise ParamError(f'{what}: число') from None
    if not math.isfinite(number):
        raise ParamError(f'{what}: конечное число')
    return number


def clean_transform(raw: Any, index: int) -> Transform:
    """Преобразование ряда из макета; пусто или старый макет без поля — без преобразования."""
    if raw in (None, '', {}):
        return Transform()
    if isinstance(raw, str):
        raw = {'op': raw}
    if not isinstance(raw, Mapping):
        raise ParamError(f'Ряд {index}: преобразование — объект с полем «op»')
    op = str(raw.get('op') or 'none')
    what = f'Ряд {index}, преобразование «{TRANSFORMS.get(op, op)}»'
    if op not in TRANSFORMS:
        raise ParamError(f'Ряд {index}: преобразование — одно из: {", ".join(TRANSFORMS.values())}')
    t: dict[str, Any] = {'op': op}
    if op == 'rolling':
        n = raw.get('n', 7)
        try:
            t['n'] = int(n)
        except (TypeError, ValueError):
            raise ParamError(f'{what}: окно — целое число') from None
        if not 1 <= t['n'] <= MAX_WINDOW:
            raise ParamError(f'{what}: окно — от 1 до {MAX_WINDOW}')
        t['by'] = str(raw.get('by') or 'points')
        if t['by'] not in ROLL_BY:
            raise ParamError(f'{what}: окно в точках или в сутках')
    if op == 'cumsum' and raw.get('season'):
        t['season'] = True
        t['overlay'] = bool(raw.get('overlay'))
    if op in ('day', 'month', 'group'):
        t['agg'] = str(raw.get('agg') or 'mean')
        if t['agg'] not in AGGS:
            raise ParamError(f'{what}: сводка — {", ".join(AGGS.values())}')
        if raw.get('cum'):
            if t['agg'] != 'sum':
                raise ParamError(f'{what}: «накопленное» только вместе со сводкой «сумма»')
            t['cum'] = True
            t['season'] = bool(raw.get('season'))
            t['overlay'] = bool(raw.get('season') and raw.get('overlay'))
    if op == 'norm':
        t['norm'] = str(raw.get('norm') or 'first')
        if t['norm'] not in NORMS:
            raise ParamError(f'{what}: нормировка — {", ".join(NORMS.values())}')
    if op in ('mul', 'div', 'add') or (op == 'norm' and t['norm'] == 'value'):
        if raw.get('value') in (None, ''):
            raise ParamError(f'{what}: введите число')
        t['value'] = _num(raw.get('value'), what)
        if op in ('div', 'norm') and t['value'] == 0:
            raise ParamError(f'{what}: делить на ноль нельзя')
    return Transform(**t)


def _same(a: float, b: float) -> bool:
    return abs(a - b) <= 2e-3 * abs(b)


def _scaled_unit(unit: str, factor: float) -> str | None:
    """Единица после умножения на ``factor`` (перевод единиц); неизвестно — ``None``."""
    for ladder in LADDERS:
        if unit in ladder:
            i = ladder.index(unit)
            for j, name in enumerate(ladder):
                if j != i and _same(factor, 1000.0 ** (i - j)):
                    return name
    for base, other, k in PRESSURE:
        if unit == base and _same(factor, k):
            return other
        if unit == other and _same(factor, 1 / k):
            return base
    return None


def _fmt(value: float) -> str:
    return f'{value:g}'.replace('.', ',')


def describe(t: Transform, label: str, unit: str, entity_word: str = 'скважинам') -> tuple[str, str]:
    """Подпись и единица ряда после преобразования. Неизвестная единица — пусто: инженер задаёт её вручную в ряду."""
    op = t.op
    if op == 'none':
        return label, unit
    if op == 'cumsum':
        return f'{label}, накопленное{" за сезон" if t.season else ""}', CUMULATIVE.get(unit, ('', 1.0))[0] if unit else ''
    if op == 'rolling':
        return f'{label}, скользящее среднее ({t.n} {ROLL_BY[t.by]})', unit
    if op in ('day', 'month', 'group'):
        where = {'day': 'за сутки', 'month': 'за месяц', 'group': f'по {entity_word}'}[op]
        new = unit
        if t.agg == 'sum' and op == 'month':
            new = CUMULATIVE.get(unit, ('', 1.0))[0] if unit else ''
        if t.cum:
            return f'{label}, {AGGS[t.agg]} {where}, накопленное{" за сезон" if t.season else ""}', CUMULATIVE.get(new, ('', 1.0))[0] if new else ''
        return f'{label}, {AGGS[t.agg]} {where}', new
    if op == 'norm':
        return f'{label} / {"первое значение" if t.norm == "first" else "максимум" if t.norm == "max" else _fmt(t.value)}', 'д. ед.'
    if op == 'add':
        return f'{label} {"+" if t.value >= 0 else "−"} {_fmt(abs(t.value))}', unit
    if op in ('mul', 'div'):
        factor = t.value if op == 'mul' else 1 / t.value
        new = _scaled_unit(unit, factor)
        if new is not None:
            return label, new
        return f'{label} {"×" if op == "mul" else "÷"} {_fmt(t.value)}', ''
    if op == 'diff':
        return f'Δ {label}', unit
    return label, unit


def _agg(values: pd.core.groupby.SeriesGroupBy, how: str) -> pd.Series:
    # сумма пустой группы — пропуск, а не ноль: «нет данных» не превращается в простой
    return values.sum(min_count=1) if how == 'sum' else getattr(values, how)()


def extend_flat(f: pd.DataFrame, end: pd.Timestamp | None, seasons: pd.Series | None) -> pd.DataFrame:
    """Накопленная кривая по датам не рвётся: в сутки без записи значение остаётся прежним (горизонтальная линия), после
    последней записи кривая тянется до ``end`` (последние сутки данных набора или конец периода ряда). В режиме «за сезон»
    каждый сезон тянется до своего конца, а между сезонами линия разрывается: следующий сезон начинается с нуля."""
    if f.empty or not pd.api.types.is_datetime64_any_dtype(f['x']):
        return f
    step = f.sort_values('x')['x'].drop_duplicates().diff().median()
    if pd.notna(step) and step > pd.Timedelta(days=1):       # по месяцам и реже — суточной сетки нет
        return f
    parts = []
    for entity, g in f.sort_values('x', kind='stable').groupby('entity', sort=False):
        g = g.drop_duplicates('x', keep='last')
        season = g['x'].dt.normalize().map(seasons) if seasons is not None else pd.Series(np.nan, index=g.index)
        blocks = [(g, end)] if seasons is None else \
            [(b, seasons[seasons.eq(name)].index.max()) for name, b in g.groupby(season, sort=False)]
        last = len(blocks) - 1
        for i, (b, stop) in enumerate(blocks):
            stop = max(b['x'].max(), stop) if stop is not None and pd.notna(stop) else b['x'].max()
            grid = pd.date_range(b['x'].min().normalize(), stop.normalize(), freq='D')
            y = b.assign(x=b['x'].dt.normalize()).set_index('x')['y'].reindex(grid).ffill()
            part = pd.DataFrame({'entity': entity, 'x': grid, 'y': y.to_numpy(), 'id': None})
            if seasons is not None and i < last:        # разрыв линии между сезонами
                part = pd.concat([part, pd.DataFrame({'entity': [entity], 'x': [stop.normalize() + pd.Timedelta(hours=12)],
                                                      'y': [np.nan], 'id': [None]})], ignore_index=True)
            parts.append(part)
    out = pd.concat(parts, ignore_index=True)
    out['date'] = out['x'].dt.normalize()
    return out


def _cumsum(f: pd.DataFrame, seasons: pd.Series | None, label: str, notes: list[Note]) -> pd.Series:
    """Нарастающий итог по кривой, заново с начала каждого сезона. Точки вне сезонов (нейтральный период, нет периода) не показываются."""
    day = f['date'] if 'date' in f else f['x']
    if seasons is None or not pd.api.types.is_datetime64_any_dtype(day):
        notes.append(Note(f'{label}: «за сезон» нужны даты и сезоны (период расхода) в данных проекта; накопленное считается без сброса.', 'warning'))
        return f.groupby('entity', sort=False)['y'].cumsum()
    season = day.dt.normalize().map(seasons)
    out = f['y'].groupby([f['entity'], season], sort=False).cumsum()
    outside = int((season.isna() & f['y'].notna()).sum())
    if outside:
        notes.append(Note(f'{label}: {outside} точек вне сезонов (нейтральный период или нет периода) не показаны; границы сезонов — период '
                          'расхода в данных проекта, их можно править в «Настройках».'))
    return out.where(season.notna())


def apply(frame: pd.DataFrame, t: Transform, unit: str, label: str, x_date: bool,
          seasons: pd.Series | None = None) -> tuple[pd.DataFrame, list[Note]]:
    """Преобразование значений Y по каждой кривой (``entity``); X сортируется. Пропуски не превращаются в нули, нули остаются."""
    notes: list[Note] = []
    if t.op == 'none' or frame.empty:
        return frame, notes
    if pd.api.types.is_datetime64_any_dtype(frame['y']):
        return frame, [Note(f'{label}: значения — даты, преобразование «{TRANSFORMS[t.op]}» не применено.', 'warning')]
    if t.op in ('day', 'month') or (t.op == 'rolling' and t.by == 'days'):
        if not x_date:
            return frame, [Note(f'{label}: «{TRANSFORMS[t.op]}» по времени — только когда X — дата; преобразование не применено.', 'warning')]
    f = frame.sort_values(['entity', 'x'], kind='stable').reset_index(drop=True)
    if 'id' not in f:
        f['id'] = None
    by = f.groupby('entity', sort=False)['y']
    if t.op == 'cumsum':
        k = CUMULATIVE.get(unit, ('', 1.0))[1]
        f['y'] = (_cumsum(f, seasons, label, notes) if t.season else by.cumsum()) * k   # пропуск остаётся пропуском (на линии разрыв), сумма идёт дальше
        if unit.endswith('/сут') and x_date:
            notes += _daily_check(f, label)
    elif t.op == 'rolling':
        if t.by == 'points':
            f['y'] = by.transform(lambda s: s.rolling(t.n, min_periods=1).mean().where(s.notna()))
        else:
            parts = []
            for _, g in f.groupby('entity', sort=False):
                r = g.set_index('x')['y'].rolling(f'{t.n}D', min_periods=1).mean().to_numpy()
                parts.append(pd.Series(np.where(g['y'].notna(), r, np.nan), index=g.index))
            f['y'] = pd.concat(parts).sort_index()
    elif t.op in ('day', 'month', 'group'):
        if t.op == 'group' and f['entity'].nunique() <= 1 and not f['entity'].iloc[0]:
            notes.append(Note(f'{label}: в наборе нет скважин — сводка по скважинам не меняет ряд.'))
        if t.op == 'day':
            f['x'] = f['x'].dt.normalize()
            keys = ['entity', 'x']
        elif t.op == 'month':
            f['x'] = f['x'].dt.to_period('M').dt.to_timestamp()
            keys = ['entity', 'x']
        else:
            wells = f['entity'].nunique()
            f['entity'] = ''
            keys = ['entity', 'x']
            notes.append(Note(f'{label}: {AGGS[t.agg]} по {wells} кривым на каждое значение X; пропуски не учитываются.'))
        out = _agg(f.groupby(keys, sort=True)['y'], t.agg).reset_index()
        if t.op == 'month' and t.agg == 'sum':
            out['y'] *= CUMULATIVE.get(unit, ('', 1.0))[1]
        out['id'] = None
        if x_date:
            out['date'] = out['x'].dt.normalize()
        elif t.op == 'group' and 'date' in f:
            out['date'] = f.groupby(keys, sort=True)['date'].first().to_numpy()
        f = out
        if t.cum:
            now = CUMULATIVE.get(unit, ('', 1.0))[0] if t.op == 'month' and unit else unit
            f = f.sort_values(['entity', 'x'], kind='stable').reset_index(drop=True)
            f['y'] = (_cumsum(f, seasons, label, notes) if t.season else f.groupby('entity', sort=False)['y'].cumsum()) \
                * CUMULATIVE.get(now, ('', 1.0))[1]
    elif t.op == 'norm':
        if t.norm == 'value':
            f['y'] = f['y'] / t.value
        else:
            base = by.transform(lambda s: s.dropna().iloc[0] if s.notna().any() else np.nan) if t.norm == 'first' \
                else by.transform(lambda s: s.abs().max())
            bad = base.eq(0) | base.isna()
            if bad.any():
                names = sorted({str(e) for e in f.loc[bad & f['y'].notna(), 'entity']})
                if names:
                    notes.append(Note(f'{label}: значение для нормировки равно нулю — кривые {", ".join(n or "объекта" for n in names[:5])} '
                                      'не показаны.', 'warning'))
            f['y'] = (f['y'] / base.where(~bad)).astype(float)
    elif t.op == 'mul':
        f['y'] = f['y'] * t.value
    elif t.op == 'div':
        f['y'] = f['y'] / t.value
    elif t.op == 'add':
        f['y'] = f['y'] + t.value
    elif t.op == 'diff':
        f['y'] = by.transform(lambda s: s.dropna().diff().reindex(s.index))
    if t.op not in KEEP_IDS:
        f['id'] = None
    return f, notes


def _daily_check(f: pd.DataFrame, label: str) -> list[Note]:
    step = f.groupby('entity', sort=False)['x'].diff().dropna()
    if len(step) and step.median() != pd.Timedelta(days=1):
        return [Note(f'{label}: точки идут не по суткам — накопленное — это сумма значений, а не объём за период.', 'warning')]
    return []


# ---------- формулы ----------

MAX_FORMULA = 500
MAX_DEPTH = 60
CONSTANTS = {'pi': math.pi, 'e': math.e}
# имя → (наименьшее и наибольшее число аргументов, описание для подсказки)
FUNCTIONS: dict[str, tuple[int, int, str]] = {
    'abs': (1, 1, 'модуль'), 'sqrt': (1, 1, 'корень'), 'ln': (1, 1, 'натуральный логарифм'),
    'log10': (1, 1, 'десятичный логарифм'), 'exp': (1, 1, 'экспонента'),
    'min': (2, 20, 'наименьшее'), 'max': (2, 20, 'наибольшее'), 'mean': (2, 20, 'среднее имеющихся'),
}
ALIASES = {'lg': 'log10', 'корень': 'sqrt', 'модуль': 'abs'}
# Кириллические буквы, неотличимые от латинских: «А/В» набрано в русской раскладке.
HOMOGLYPHS = str.maketrans('АВСЕНКМОРТХ', 'ABCEHKMOPTX')
SYMBOLS = str.maketrans({'×': '*', '·': '*', '÷': '/', '−': '-', '–': '-', '—': '-', ' ': ' '})
TOKEN = re.compile(r'\s*(?:(?P<num>[0-9]+(?:[.,][0-9]+)?(?:[eE][+-]?[0-9]+)?|[.,][0-9]+)|(?P<name>[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё_0-9]*)'
                   r'|(?P<op>\*\*|[-+*/^();,]))')
REF = re.compile(r'^(?:[A-Z]|R([0-9]{1,3}))$')


def letter(index: int) -> str:
    """Буква ряда: 1 → A, 26 → Z, дальше R27."""
    return chr(64 + index) if index <= 26 else f'R{index}'


class _Parser:
    def __init__(self, text: str, where: str, original: str):
        self.where, self.src = where, original
        self.tokens: list[tuple[str, str, int]] = []
        pos = 0
        while pos < len(text):
            if text[pos:].strip() == '':
                break
            m = TOKEN.match(text, pos)
            if not m:
                bad = text[pos:].lstrip()[0]
                at = text.index(bad, pos)
                hint = ' — у рядов нет полей через точку' if bad == '.' else ''
                raise self.error(f'недопустимый символ «{bad}»{hint}', at)
            kind = m.lastgroup or ''
            self.tokens.append((kind, m.group(kind), m.start(kind)))
            pos = m.end()
        self.i = 0
        self.depth = 0

    def error(self, text: str, at: int | None = None) -> ParamError:
        where = f' (знак {at + 1})' if at is not None else ''
        return ParamError(f'{self.where}: {text}{where}. Формула: «{self.src}»')

    def peek(self) -> tuple[str, str, int] | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def take(self, value: str | None = None) -> tuple[str, str, int]:
        tok = self.peek()
        if tok is None:
            raise self.error('формула обрывается — допишите выражение' if value is None else f'не хватает «{value}»')
        if value is not None and tok[1] != value:
            raise self.error(f'ожидается «{value}», а стоит «{tok[1]}»', tok[2])
        self.i += 1
        return tok

    def parse(self) -> tuple:
        if not self.tokens:
            raise self.error('пустая формула')
        node = self.expr()
        tok = self.peek()
        if tok is not None:
            raise self.error(f'лишнее «{tok[1]}» — не хватает знака операции или скобки', tok[2])
        return node

    def nest(self) -> None:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise self.error('слишком глубокая вложенность скобок')

    def expr(self) -> tuple:
        self.nest()
        node = self.term()
        while (tok := self.peek()) and tok[1] in '+-' and tok[0] == 'op':
            self.i += 1
            node = ('bin', tok[1], node, self.term())
        self.depth -= 1
        return node

    def term(self) -> tuple:
        node = self.unary()
        while (tok := self.peek()) and tok[0] == 'op' and tok[1] in ('*', '/'):
            self.i += 1
            node = ('bin', tok[1], node, self.unary())
        return node

    def unary(self) -> tuple:
        tok = self.peek()
        if tok and tok[0] == 'op' and tok[1] in '+-':
            self.i += 1
            self.nest()
            inner = self.unary()
            self.depth -= 1
            return ('neg', inner) if tok[1] == '-' else inner
        return self.power()

    def power(self) -> tuple:
        base = self.atom()
        tok = self.peek()
        if tok and tok[0] == 'op' and tok[1] in ('^', '**'):
            self.i += 1
            self.nest()
            node = ('bin', '^', base, self.unary())      # справа налево: 2^3^2 = 2^9, 2^-1 — можно
            self.depth -= 1
            return node
        return base

    def atom(self) -> tuple:
        tok = self.take()
        kind, value, at = tok
        if kind == 'num':
            return ('num', float(value.replace(',', '.')))
        if kind == 'op' and value == '(':
            node = self.expr()
            self.take(')')
            return node
        if kind == 'name':
            nxt = self.peek()
            if nxt and nxt[1] == '(':
                name = ALIASES.get(value.lower(), value.lower())
                if name not in FUNCTIONS:
                    hint = ' — для логарифма есть ln и log10' if name == 'log' else ''
                    raise self.error(f'неизвестная функция «{value}»{hint}; есть: {", ".join(FUNCTIONS)}', at)
                self.i += 1
                args = [] if self.peek() and self.peek()[1] == ')' else [self.expr()]
                while self.peek() and self.peek()[1] in (';', ','):
                    self.i += 1
                    args.append(self.expr())
                self.take(')')
                low, high, _ = FUNCTIONS[name]
                if not low <= len(args) <= high:
                    count = f'{low}' if low == high else f'от {low}'
                    raise self.error(f'у функции {name} аргументов: {count}, а задано {len(args)} (аргументы — через «;»)', at)
                return ('call', name, args)
            if value in CONSTANTS:
                return ('num', CONSTANTS[value])
            ref = value.translate(HOMOGLYPHS)
            m = REF.match(ref)
            if m:
                return ('ref', int(m.group(1)) if m.group(1) else ord(ref) - 64, at, value)
            raise self.error(f'неизвестное имя «{value}»: ряды — заглавные буквы A, B, C… (или R1, R2…), '
                             f'функции — {", ".join(FUNCTIONS)}, постоянные — pi, e', at)
        raise self.error(f'ожидается число, ряд или «(», а стоит «{value}»', at)


@dataclass(frozen=True)
class Formula:
    text: str
    tree: tuple
    refs: tuple[int, ...]         # номера рядов в порядке появления, без повторов


def _refs(node: tuple, out: list[tuple[int, str]]) -> None:
    if node[0] == 'ref':
        out.append((node[1], node[3]))
    elif node[0] == 'neg':
        _refs(node[1], out)
    elif node[0] == 'bin':
        _refs(node[2], out)
        _refs(node[3], out)
    elif node[0] == 'call':
        for a in node[2]:
            _refs(a, out)


def parse_formula(text: str, index: int, rows: int) -> Formula:
    """Разбор формулы ряда ``index``; ``rows`` — число рядов макета. Ошибка — ``ParamError`` по-русски с номером ряда."""
    where = f'Ряд {index}, формула'
    if len(text) > MAX_FORMULA:
        raise ParamError(f'{where}: не длиннее {MAX_FORMULA} знаков')
    p = _Parser(text.translate(SYMBOLS), where, text)
    tree = p.parse()
    found: list[tuple[int, str]] = []
    _refs(tree, found)
    if not found:
        raise ParamError(f'{where}: нет ни одного ряда — укажите ряды буквами (A — ряд 1, B — ряд 2…). Формула: «{text}»')
    for ref, name in found:
        if ref < 1 or ref > rows:
            raise ParamError(f'{where}: ряда {name} (№ {ref}) нет — в макете рядов: {rows}. Формула: «{text}»')
    return Formula(text, tree, tuple(dict.fromkeys(r for r, _ in found)))


def check_cycles(formulas: Mapping[int, Formula]) -> None:
    """Ряд-формула не может ссылаться на себя, прямо или через другие формулы."""
    state: dict[int, int] = {}

    def visit(i: int, path: list[int]) -> None:
        if state.get(i) == 2 or i not in formulas:
            return
        if state.get(i) == 1:
            loop = path[path.index(i):] + [i]
            raise ParamError(f'Ряд {loop[0]}: циклическая ссылка в формулах — '
                             f'{" → ".join(f"{letter(n)} (ряд {n})" for n in loop)}. Уберите ссылку на самого себя.')
        state[i] = 1
        for r in formulas[i].refs:
            visit(r, path + [i])
        state[i] = 2

    for i in sorted(formulas):
        visit(i, [])


SKIPS = {'div0': 'деление на ноль', 'log': 'логарифм от нуля или отрицательного', 'sqrt': 'корень из отрицательного',
         'pow': 'степень без значения', 'big': 'слишком большое число'}


def evaluate(tree: tuple, env: Mapping[int, np.ndarray], size: int) -> tuple[np.ndarray, dict[str, int]]:
    """Значение формулы на выровненных массивах рядов; недопустимые точки — NaN и счётчик причин (только где входы были)."""
    counts = {k: 0 for k in SKIPS}

    def mark(reason: str, mask: np.ndarray) -> None:
        counts[reason] += int(np.count_nonzero(mask))

    def run(node: tuple) -> np.ndarray:
        kind = node[0]
        if kind == 'num':
            return np.full(size, node[1], dtype=float)
        if kind == 'ref':
            return env[node[1]]
        if kind == 'neg':
            return -run(node[1])
        if kind == 'bin':
            a, b = run(node[2]), run(node[3])
            ok = np.isfinite(a) & np.isfinite(b)
            with np.errstate(all='ignore'):
                if node[1] == '+':
                    return a + b
                if node[1] == '-':
                    return a - b
                if node[1] == '*':
                    return a * b
                if node[1] == '/':
                    zero = ok & (b == 0)
                    mark('div0', zero)
                    return np.where(zero, np.nan, a / np.where(b == 0, 1, b))
                out = np.power(a, b)
                bad = ok & ~np.isfinite(out)
                mark('pow', bad)
                return np.where(bad, np.nan, out)
        name, args = node[1], [run(a) for a in node[2]]
        x = args[0]
        ok = np.isfinite(x)
        with np.errstate(all='ignore'):
            if name == 'abs':
                return np.abs(x)
            if name == 'sqrt':
                bad = ok & (x < 0)
                mark('sqrt', bad)
                return np.sqrt(np.where(bad, np.nan, x))
            if name in ('ln', 'log10'):
                bad = ok & (x <= 0)
                mark('log', bad)
                safe = np.where(bad, np.nan, x)
                return np.log(safe) if name == 'ln' else np.log10(safe)
            if name == 'exp':
                out = np.exp(x)
                bad = ok & ~np.isfinite(out)
                mark('big', bad)
                return np.where(bad, np.nan, out)
            stack = np.vstack(args)
            if name == 'mean':
                present = np.isfinite(stack)
                n = present.sum(axis=0)
                return np.where(n > 0, np.where(present, stack, 0).sum(axis=0) / np.where(n > 0, n, 1), np.nan)
            fn: Callable[..., np.ndarray] = np.minimum if name == 'min' else np.maximum
            out = stack[0]
            for row in stack[1:]:
                out = fn(out, row)        # пропуск в любом аргументе — пропуск (как «нет данных»)
            return out

    out = run(tree).astype(float)
    out[~np.isfinite(out)] = np.nan
    return out, counts


# ---------- выравнивание рядов формулы ----------

FORMULA_KEYS = {'well_date': 'скважина + дата', 'date': 'дата', 'well': 'скважина', 'nearest': 'ближайшая дата'}


@dataclass
class Part:
    """Посчитанный ряд для формулы: точки (entity, x, y, id, date) и чем делится на кривые."""
    frame: pd.DataFrame
    entity_kind: str


def align(base: Part, other: Part, key: str, days: int, label: str, name: str) -> tuple[np.ndarray, list[Note]]:
    """Значения ``other`` на точках ``base`` по ключу формулы; несколько на ключ — среднее."""
    notes: list[Note] = []
    b, o = base.frame, other.frame
    shared = bool(base.entity_kind) and base.entity_kind == other.entity_kind
    has_dates = 'date' in b and 'date' in o and b['date'].notna().any() and o['date'].notna().any()
    if key in ('well_date', 'well') and not shared:
        if key == 'well' or not has_dates:
            notes.append(Note(f'{label}: у ряда {name} нет общей со вторым рядом колонки скважин — по скважине не сопоставить. '
                              'Выберите ключ «дата».', 'warning'))
            return np.full(len(b), np.nan), notes
        notes.append(Note(f'{label}: у ряда {name} нет деления по скважинам — сопоставлен только по дате.'))
        key = 'date'
    if key != 'well' and not has_dates:
        notes.append(Note(f'{label}: у ряда {name} или первого ряда формулы нет дат — выберите ключ «скважина».', 'warning'))
        return np.full(len(b), np.nan), notes
    left = b[['entity'] + (['date'] if 'date' in b else [])].copy()
    right = o[['entity', 'y'] + (['date'] if 'date' in o else [])].copy()
    if base.entity_kind == 'group' and shared:
        left['entity'] = left['entity'].map(group_key)
        right['entity'] = right['entity'].map(group_key)
    right = right[right['y'].notna()]
    if key == 'nearest':
        by = ['entity'] if shared else []
        r = right.dropna(subset=['date']).groupby(by + ['date'], as_index=False)['y'].mean().sort_values('date', kind='stable')
        lft = left.reset_index().dropna(subset=['date']).sort_values('date', kind='stable')
        if not len(lft) or not len(r):
            return np.full(len(b), np.nan), notes
        merged = pd.merge_asof(lft, r if shared else r.drop(columns=['entity'], errors='ignore'), on='date', by=by or None,
                               tolerance=pd.Timedelta(days=days), direction='nearest')
        values = pd.Series(np.nan, index=left.index)
        values.loc[merged['index'].to_numpy()] = merged['y'].to_numpy()
        return values.to_numpy(dtype=float), notes
    on = {'well_date': ['entity', 'date'], 'date': ['date'], 'well': ['entity']}[key]
    r = right.dropna(subset=[c for c in on if c == 'date'])
    grouped = r.groupby(on, as_index=False)['y'].mean()
    if len(grouped) < len(r):
        notes.append(Note(f'{label}: у ряда {name} на один ключ «{FORMULA_KEYS[key]}» несколько значений — взято среднее '
                          f'({len(r) - len(grouped)} строк объединено).'))
    merged = left.reset_index().merge(grouped, on=on, how='left').set_index('index').reindex(left.index)
    return merged['y'].to_numpy(dtype=float), notes


def compute(formula: Formula, parts: Mapping[int, Part | None], key: str, days: int, index: int) -> tuple[Part | None, list[Note]]:
    """Ряд-формула: точки — точки первого ряда формулы (его X, скважины, даты), остальные ряды подставляются по ключу."""
    label = f'Ряд {index}'
    notes: list[Note] = []
    for r in formula.refs:
        part = parts.get(r)
        if part is None or part.frame.empty:
            return None, [Note(f'{label}: ряд {letter(r)} (ряд {r}) пуст — формула «{formula.text}» не посчитана.')]
        if pd.api.types.is_datetime64_any_dtype(part.frame['y']):
            return None, [Note(f'{label}: значения ряда {letter(r)} — даты; в формуле только числа.', 'warning')]
    base = parts[formula.refs[0]]
    assert base is not None
    env: dict[int, np.ndarray] = {formula.refs[0]: base.frame['y'].to_numpy(dtype=float)}
    for r in formula.refs[1:]:
        other = parts[r]
        assert other is not None
        env[r], more = align(base, other, key, days, label, f'{letter(r)} (ряд {r})')
        notes += more
    y, counts = evaluate(formula.tree, env, len(base.frame))
    inputs = np.vstack(list(env.values()))
    missing = int((~np.isfinite(inputs)).any(axis=0).sum())
    skipped = {k: v for k, v in counts.items() if v}
    if skipped:
        notes.append(Note(f'{label}: пропущено точек: {sum(skipped.values())} — '
                          + ', '.join(f'{SKIPS[k]}: {v}' for k, v in skipped.items()) + '.'))
    if len(formula.refs) > 1 and missing:
        notes.append(Note(f'{label}: точек без значения хотя бы одного ряда формулы: {missing} (пропуск, по ключу «{FORMULA_KEYS[key]}»).'))
    frame = base.frame.copy()
    frame['y'] = y
    frame['id'] = None
    return Part(frame, base.entity_kind), notes


def overlay_seasons(f: pd.DataFrame, seasons: pd.Series) -> pd.DataFrame:
    """Сезоны друг на друге: X — номер суток от начала сезона (с 1), каждый сезон (и скважина) — своя кривая."""
    f = f[f['y'].notna()].copy()
    season = f['x'].dt.normalize().map(seasons)
    f = f[season.notna()].copy()
    season = season[season.notna()]
    start = season.map({name: seasons[seasons.eq(name)].index.min() for name in season.unique()})
    f['x'] = (f['x'].dt.normalize() - start).dt.days + 1
    f['entity'] = [str(name) if not str(e) else f'{e} · {name}' for e, name in zip(f['entity'], season)]
    return f.reset_index(drop=True)
