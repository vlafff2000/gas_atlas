"""Проверка качества рисунка графика перед выгрузкой: что на нём читается плохо.

Вход — сцена файла (``atlas/engine/core/export_scene.py``: элементы с именами и рамками в долях сохранённого рисунка) и сам
график. Выход — список находок::

    {'key': 'overlap:legend|title', 'code': 'overlap', 'level': 'warn', 'text': 'Легенда и заголовок накладываются…',
     'elements': ['legend', 'title']}

Находка — подсказка, а не запрет: файл выгружается в любом случае, а инженер может снять находку («не показывать») — её ключ
ложится в оформление этого графика (``checks.skip``), и она возвращается с пометкой ``skipped``, а не пропадает. Ключ постоянен:
он собран из кода проверки и имён элементов сцены, поэтому снятая находка не всплывает после перерисовки.

Уровни: ``warn`` — на рисунке что-то закрыто, обрезано или не читается; ``info`` — стоит посмотреть."""
from __future__ import annotations

import math
from typing import Any, Iterable, Mapping, Sequence

from .contract import Chart
from .engine.core.export_scene import Names

# Пороги. Размеры — в миллиметрах и пунктах рисунка в натуральную величину (``scale`` — во сколько раз рисунок уменьшат на листе).
OVERLAP_MM = 0.7            # наложение текстов: общая часть рамок шире и выше этого…
OVERLAP_SHARE = 0.4         # …и не меньше этой доли высоты меньшей рамки (рамка текста включает поля над и под буквами)
EDGE = 0.004                # за край рисунка: рамка выходит дальше этой доли
SMALL_PT = 6.0              # мельче этого на бумаге читается с трудом
PAGE_MM = 170.0             # ширина текста листа A4: рисунок шире при вставке в отчёт уменьшат до неё
PLOT_SHARE = 0.3            # область построения меньше этой доли рисунка
FLAT_SHARE = 0.2            # кривые шкалы занимают меньше этой доли высоты поля…
FLAT_MIN = 0.012            # …но это не прямая линия (у неё высота — толщина линии)
FIX_LIMIT = 500             # столько подписей прячет одно исправление
SHOWN = 12                  # столько имён элементов держит одна сводная находка

TITLES = {'overlap': 'Наложение', 'off-edge': 'Выход за край', 'small-font': 'Мелкий шрифт', 'ticks': 'Тесные деления',
          'legend-on-plot': 'Легенда на поле', 'small-plot': 'Тесное поле', 'flat': 'Сжатые кривые', 'outlier': 'Выброс',
          'empty': 'Нет данных'}
LEVELS = ('warn', 'info')
AXES = {'x': 'X', 'y': 'Y', 'y2': 'Y2', 'y3': 'Y3', 'y4': 'Y4', 'y5': 'Y5'}
TEXTS = ('title', 'subtitle', 'legend', 'axis-title', 'label', 'annotation-text')      # то, что читают: наложение этих элементов — находка


def _cut(text: Any, limit: int = 40) -> str:
    line = ' '.join(str(text or '').split())
    return line if len(line) <= limit else line[:limit - 1] + '…'


def element_title(e: Mapping[str, Any]) -> str:
    """Имя элемента для человека — то же, что в предпросмотре (``web/src/exportStage.ts: elementTitle``)."""
    kind, quoted = e.get('kind'), f' «{_cut(e["text"])}»' if e.get('text') else ''
    axis = AXES.get(str(e.get('axis') or ''), str(e.get('axis') or ''))
    return {'plot': 'Область построения', 'title': 'Заголовок' + quoted, 'subtitle': 'Подзаголовок' + quoted, 'legend': 'Легенда',
            'legend-item': 'Пункт легенды' + quoted, 'axis': f'Подписи делений оси {axis}'.strip(), 'tick': f'Подписи делений оси {axis}'.strip(), 'axis-title': f'Название оси {axis}'.strip() + quoted,
            'series': f'Ряд «{_cut(e.get("series"))}»', 'label': f'Подпись{quoted} ряда «{_cut(e.get("series"))}»',
            'annotation': 'Линия или полоса аннотации', 'annotation-text': 'Текст аннотации' + quoted}.get(str(kind), str(e.get('id')))


def _low(title: str) -> str:
    """Имя элемента в середине фразы: с маленькой буквы («…и легенда»), буква оси остаётся большой."""
    return title[:1].lower() + title[1:]


def _finding(code: str, level: str, text: str, elements: Iterable[str], key: str = '') -> dict[str, Any]:
    names = list(dict.fromkeys(elements))
    return {'key': f'{code}:{key}' if key else code, 'code': code, 'level': level, 'text': text, 'elements': names}


def _common(a: Sequence[float], b: Sequence[float]) -> tuple[float, float]:
    """Ширина и высота общей части двух рамок (в долях рисунка); нет общей части — отрицательные."""
    return min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])


def _plural(n: int, one: str, few: str, many: str) -> str:
    tail = n % 100
    return one if n % 10 == 1 and tail != 11 else few if n % 10 in (2, 3, 4) and tail not in (12, 13, 14) else many


def _overlaps(texts: list[dict[str, Any]], width: float, height: float) -> list[dict[str, Any]]:
    """Наложения читаемых элементов. Подписи точек между собой дают одну сводную находку (их бывают десятки), подписи точек
    на другом элементе — по находке на элемент, остальные пары — по находке на пару."""
    def clash(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
        w, h = _common(a['box'], b['box'])
        low = min(a['box'][3] - a['box'][1], b['box'][3] - b['box'][1])
        return w * width > OVERLAP_MM and h * height > OVERLAP_MM and h > OVERLAP_SHARE * low

    out: list[dict[str, Any]] = []
    pairs = 0
    crowded: list[str] = []
    onto: dict[str, list[str]] = {}
    hide: list[str] = []      # какие подписи спрятать, чтобы остальные читались: из каждой тесной пары — вторая по X
    order = sorted(texts, key=lambda e: e['box'][0])      # заметание по X: сравниваются только рамки, пересекающиеся по ширине
    for i, a in enumerate(order):
        for b in order[i + 1:]:
            if b['box'][0] >= a['box'][2]:
                break
            if a['id'] == b['id'] or not clash(a, b):
                continue
            labels = [e for e in (a, b) if e['kind'] == 'label']
            if len(labels) == 2:
                pairs += 1
                crowded += [a['id'], b['id']]
                if a['id'] not in hide and b['id'] not in hide:
                    hide.append(b['id'])
            elif len(labels) == 1:
                other = b if labels[0] is a else a
                onto.setdefault(other['id'], []).append(labels[0]['id'])
            elif a['kind'] == b['kind'] == 'tick':
                continue            # деления разных осей рядом в углу поля: так рисуется любой график
            else:
                first, second = sorted((a, b), key=lambda e: e['id'])
                out.append(_finding('overlap', 'warn', f'{element_title(first)} и {_low(element_title(second))} '
                                    'накладываются: один текст закрывает другой.', [first['owner'], second['owner']], f'{first["owner"]}|{second["owner"]}'))
    by_id = {e['id']: e for e in texts}
    for other, labels in onto.items():
        n = len(set(labels))
        out.append(_finding('overlap', 'warn', f'{element_title(by_id[other])} и подписи точек накладываются: {n} {_plural(n, "подпись", "подписи", "подписей")}.',
                            [by_id[other]['owner'], *labels[:SHOWN]], f'labels|{by_id[other]["owner"]}') | {'_hide': list(dict.fromkeys(labels))})
    if pairs:
        out.append(_finding('overlap', 'warn', f'Подписи точек накладываются друг на друга: {pairs} {_plural(pairs, "пара", "пары", "пар")}. '
                            'Часть подписей можно скрыть или отодвинуть.', crowded[:SHOWN], 'labels') | {'_hide': hide})
    return out


def _ticks(axis: Mapping[str, Any], width: float, height: float) -> dict[str, Any] | None:
    """Подписи делений одной оси налезают друг на друга. У наклонных подписей рамка шире самого текста и рамки соседей
    пересекаются всегда, поэтому для них считается расстояние между строками: шаг подписей поперёк направления текста."""
    across = axis.get('axis') == 'x'
    boxes = sorted(axis.get('ticks') or (), key=lambda b: b[0] + b[2] if across else b[1] + b[3])
    if len(boxes) < 2:
        return None
    angle = math.radians(float(axis.get('rotation') or 0))
    turned = abs(math.sin(angle)) > 0.05 and abs(math.cos(angle)) > 0.05
    line = (axis.get('size') or 0) * 25.4 / 72      # высота строки, мм
    tight = 0
    for a, b in zip(boxes, boxes[1:]):
        w, h = _common(a, b)
        if not (w * width > 0.1 and h * height > 0.1):
            continue
        if turned:
            step = ((b[0] + b[2]) - (a[0] + a[2])) / 2 * width if across else ((b[1] + b[3]) - (a[1] + a[3])) / 2 * height
            tight += step * abs(math.sin(angle) if across else math.cos(angle)) < line * 0.85
        else:
            tight += 1
    if not tight:
        return None
    name = AXES.get(str(axis.get('axis')), str(axis.get('axis')))
    return _finding('ticks', 'warn', f'Подписи делений оси {name} налезают друг на друга ({tight} из {len(boxes) - 1} соседних пар): '
                    'увеличьте шаг делений, поверните подписи или уменьшите шрифт.', [axis['id']], axis['id'])


def _numbers(values: Any) -> list[float]:
    out = []
    for v in values if values is not None else ():
        try:
            number = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            out.append(number)
    return out


def _data(chart: Chart) -> list[dict[str, Any]]:
    """Находки по данным графика: пустые ряды и шкалы, выбросы (подсказка автоподбора осей, ``atlas/axis_auto.py``)."""
    out: list[dict[str, Any]] = []
    if chart.heat is not None or chart.figure is not None:
        return out
    names = Names()
    filled: dict[str, int] = {}
    empty: list[str] = []
    for s in chart.series:
        key = names.series(s.name)
        has = bool(_numbers(s.y)) or s.kind == 'box' and len(s.y) > 0
        filled[s.axis or 'y'] = filled.get(s.axis or 'y', 0) + has
        if not has:
            empty.append(key)
    if not chart.series or len(empty) == len(chart.series):
        return [_finding('empty', 'warn', 'На графике нет данных: все ряды пусты.', ['plot'], 'chart')]
    for key in empty:
        out.append(_finding('empty', 'info', f'Ряд «{_cut(key)}» пуст: на графике его нет, а в легенде он может остаться.', [f'series:{key}'], f'series:{key}'))
    for name in chart.axis_names():
        if not filled.get(name):
            out.append(_finding('empty', 'info', f'Шкала {AXES.get(name, name)} без данных: у её рядов нет чисел.', [f'axis:{name}'], f'axis:{name}'))
        axis = chart.axis_at(name)
        auto = axis.auto or {}
        for hint in auto.get('hints') or ():
            if hint.get('kind') == 'outlier' and (axis.minimum, axis.maximum) == (auto.get('min'), auto.get('max')):      # пределы не заданы вручную
                n, share = int(hint.get('count') or 0), max(1, round(float(hint.get('share') or 0) * 100))
                out.append(_finding('outlier', 'info', f'Шкала {AXES.get(name, name)}: {n} {_plural(n, "выброс", "выброса", "выбросов")} '
                                    f'{_plural(n, "сжимает", "сжимают", "сжимают")} остальные точки до {"менее чем " if share == 1 else ""}{share} % высоты поля. '
                                    'Пределы оси можно задать вручную в «Формате» оси.', [f'axis:{name}'], f'axis:{name}'))
    return out


def _fix(found: dict[str, Any], placed: Mapping[str, Any], by_id: Mapping[str, Mapping[str, Any]]) -> None:
    """Предложение исправления в один щелчок: ``fix = {'text', 'places': {имя элемента: None | {'hide': True}}}``. ``None`` — вернуть
    элемент на автоматическое место (сдвинутый рукой элемент — самая частая причина наложения), ``hide`` — спрятать лишние подписи
    точек. Применяет исправление инженер, одним шагом отмены; сервер ничего не меняет сам."""
    hide = found.pop('_hide', None) or []
    back = [name for name in found['elements'] if (placed.get(name) or {}).get('dx') or (placed.get(name) or {}).get('dy')]
    if found['code'] in ('overlap', 'off-edge') and back:
        names = ', '.join(_low(element_title(by_id[n])) if n in by_id else n for n in back[:3])
        found['fix'] = {'text': f'Вернуть на место: {names}', 'places': {name: None for name in back}}
    elif found['code'] == 'overlap' and hide:
        n = len(hide)
        found['fix'] = {'text': f'Скрыть {n} {_plural(n, "подпись", "подписи", "подписей")}', 'places': {name: {'hide': True} for name in hide[:FIX_LIMIT]}}


def check(scene: Sequence[Mapping[str, Any]], chart: Chart | None = None, skip: Iterable[str] = (), page_mm: float | None = PAGE_MM) -> list[dict[str, Any]]:
    """Находки по сцене рисунка и по данным графика. ``skip`` — ключи (или коды проверок), снятые инженером: такие находки
    возвращаются с ``skipped: True``. ``page_mm`` — ширина места на листе: рисунок шире уменьшат до неё, и шрифт проверяется
    уже уменьшенным (``None`` — рисунок останется в натуральную величину)."""
    shown = [e for e in scene if e.get('box') and not e.get('hidden') and not e.get('missing')]
    by_id = {e['id']: e for e in shown}
    plot = by_id.get('plot')
    width, height = (plot.get('mm') or (160.0, 100.0)) if plot else (160.0, 100.0)      # рисунок в миллиметрах
    scale = min(1.0, page_mm / width) if page_mm and width > 0 else 1.0
    out: list[dict[str, Any]] = []

    texts = [{**e, 'owner': e['id']} for e in shown if e['kind'] in TEXTS]
    for axis in (e for e in shown if e['kind'] == 'axis'):
        texts += [{'id': f'{axis["id"]}#{i}', 'owner': axis['id'], 'kind': 'tick', 'axis': axis.get('axis'), 'box': box} for i, box in enumerate(axis.get('ticks') or ())]
    found = _overlaps(texts, width, height)
    seen: set[str] = set()
    for one in found:      # деление оси в находке называется осью: по одной находке на пару «элемент — ось»
        if one['key'] not in seen:
            seen.add(one['key'])
            out.append(one)

    for e in shown:
        x0, y0, x1, y1 = e['box']
        if e['kind'] in ('plot', 'series', 'annotation', 'legend-item'):
            continue
        if min(x0, y0) < -EDGE or max(x1, y1) > 1 + EDGE:
            out.append(_finding('off-edge', 'warn', f'{element_title(e)}: часть элемента за краем рисунка, в файле она будет обрезана.', [e['id']], e['id']))

    small = [e for e in shown if e.get('size') and e['size'] * scale < SMALL_PT]
    if small:      # одна находка на рисунок: мелкий шрифт обычно у всего сразу (рисунок слишком широк для листа)
        labels = sum(e['kind'] == 'label' for e in small)
        names = list(dict.fromkeys(_low(element_title({**e, 'text': ''})) for e in small if e['kind'] != 'label')) + ([f'подписи точек ({labels})'] if labels else [])
        size = f'{min(e["size"] for e in small) * scale:.1f}'.replace('.', ',')
        where = f' после уменьшения рисунка до ширины листа ({page_mm:g} мм)' if scale < 1 else ''
        out.append(_finding('small-font', 'warn', f'Мелкий шрифт, от {size} пт{where}: {", ".join(names)}. Мельче {SMALL_PT:g} пт на бумаге читается с трудом; '
                            'задайте рисунку ширину под лист или увеличьте шрифт.', [e['id'] for e in small[:SHOWN]]))

    for axis in (e for e in shown if e['kind'] == 'axis'):
        one = _ticks(axis, width, height)
        if one:
            out.append(one)

    if plot:
        px0, py0, px1, py1 = plot['box']
        share = max(0.0, px1 - px0) * max(0.0, py1 - py0)
        if share < PLOT_SHARE:
            out.append(_finding('small-plot', 'info', f'Область построения занимает {round(share * 100)} % рисунка: место отнимают легенда, заголовки и подписи. '
                                'Легенду можно переставить или скрыть, рисунок сделать крупнее.', ['plot']))
        for legend in (e for e in shown if e['kind'] == 'legend'):
            w, h = _common(legend['box'], plot['box'])
            if w > 0 and h > 0 and w * h > 0.5 * (legend['box'][2] - legend['box'][0]) * (legend['box'][3] - legend['box'][1]):
                out.append(_finding('legend-on-plot', 'info', 'Легенда стоит поверх области построения: проверьте, что она не закрывает кривые и подписи.',
                                    [legend['id']], legend['id']))
        tall = py1 - py0
        spans: dict[str, list[Mapping[str, Any]]] = {}
        for s in (e for e in shown if e['kind'] == 'series'):
            spans.setdefault(str(s.get('axis') or 'y'), []).append(s)
        for name, group in spans.items():
            part = (max(s['box'][3] for s in group) - min(s['box'][1] for s in group)) / tall if tall > 0 else 1.0
            if FLAT_MIN < part < FLAT_SHARE:
                out.append(_finding('flat', 'info', f'Кривые шкалы {AXES.get(name, name)} занимают {round(part * 100)} % высоты поля: изменений почти не видно. '
                                    'Проверьте пределы оси.', [f'axis:{name}', *(s['id'] for s in group[:SHOWN])], f'axis:{name}'))

    if chart is not None:
        out += _data(chart)
    placed = (chart.style.get('elements') or {}) if chart is not None else {}
    for one in out:
        _fix(one, placed, by_id)
    off = set(skip)
    for one in out:
        if one['key'] in off or one['code'] in off:
            one['skipped'] = True
    return sorted(out, key=lambda f: (bool(f.get('skipped')), LEVELS.index(f['level'])))


def summary(findings: Sequence[Mapping[str, Any]]) -> str:
    """Одна строка для отчёта выгрузки: сколько находок не снято инженером."""
    live = [f for f in findings if not f.get('skipped')]
    if not live:
        return ''
    n = len(live)
    return f'Проверка качества: {n} {_plural(n, "замечание", "замечания", "замечаний")} ({"; ".join(dict.fromkeys(TITLES[f["code"]].lower() for f in live))}).'
