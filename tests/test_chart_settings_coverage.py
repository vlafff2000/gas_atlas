"""Покрытие настроек графика: каждая настройка модели ``chart_style`` достижима из окна «Формат» (или названа в списке известных пробелов).

Тест читает исходники интерфейса (``web/src``) и сверяет их с моделью, чтобы новая настройка не осталась «записанной, но недоступной».
Новая настройка в ``chart_style.py`` без поля в ``FormatFields.tsx`` / ``ChartSettings.tsx`` ломает этот тест.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from atlas import chart_style as cs

WEB = Path(__file__).resolve().parents[1] / 'web' / 'src'
FORMAT_FILES = ('FormatFields.tsx', 'ChartSettings.tsx', 'FormatPane.tsx')
SETTER = r'(?:set\w*|onChange|edit|patch)\(\s*(?:[\w.]+,\s*)?\{[^}]*\b%s\b\s*:'


def _text(*names: str) -> str:
    return ''.join((WEB / n).read_text(encoding='utf8') for n in names)


FORMAT_SRC = _text(*FORMAT_FILES)

# Известные пробелы: настройка есть в модели и работает, но в окне «Формат» поля для неё нет (пока только «cross»). Убрать из списка, когда поле появится в «Формат».
KNOWN_GAPS = {'cross', 'break_from', 'break_to', 'markerColor'}
# markerColor и break_*: поле есть, но записывается не через set({...}) прямого вида (см. ChartSettings, разрыв оси в FormatPane)
SPECIAL_OK = {'markerColor': 'markerColor', 'break_from': 'break_from', 'break_to': 'break_to'}


def _reachable(key: str) -> bool:
    if key in SPECIAL_OK:
        return re.search(r'\b%s\b' % key, FORMAT_SRC) is not None
    return re.search(SETTER % re.escape(key), FORMAT_SRC) is not None


GROUPS = {
    'series (Look)': cs.LOOK,
    'axis (AXIS_FMT)': cs.AXIS_FMT,
    'chart (CHART_FMT)': cs.CHART_FMT,
    'annotation': cs.ANNOTATION,
}


@pytest.mark.parametrize('group', GROUPS)
def test_every_setting_has_a_field(group):
    missing = sorted(k for k in GROUPS[group] if not _reachable(k))
    assert not missing, f'настройки {group} без поля в окне «Формат»: {missing}'


def test_scale_keys_reachable_somewhere():
    """Границы, шаг, логарифм, обратное направление: поле хотя бы в одном окне (график или конструктор)."""
    src = _text('BuilderDialogs.tsx', 'ChartView.tsx') + FORMAT_SRC
    keys = set(cs.AXIS_SCALE_KEYS) | {'log', 'inverse', 'from_zero'}
    missing = sorted(k for k in keys if not re.search(r'\b%s\b' % k, src))
    assert not missing, f'настройки оси без поля нигде: {missing}'


def test_known_gaps_are_real():
    """Список пробелов не устаревает: если поле в «Формат» появилось, строка из KNOWN_GAPS удаляется."""
    stale = sorted(k for k in KNOWN_GAPS - set(SPECIAL_OK) if re.search(SETTER % re.escape(k), FORMAT_SRC))
    assert not stale, f'уже есть в «Формат», уберите из KNOWN_GAPS: {stale}'


# --- по видам рядов -------------------------------------------------------------------------------------------------

def _blocks(src: str) -> list[tuple[str, set[str]]]:
    """Условные блоки ``{guard && <fieldset> ... </fieldset>}``: (условие, ключи, которые в них записываются)."""
    out = []
    for m in re.finditer(r'\{([^{}<>]+?) && <fieldset>(.*?)</fieldset>\}', src, re.S):
        keys = set(re.findall(r'(?:set\w*|onChange)\(\s*\{\s*(\w+)\s*:', m.group(2)))
        keys |= set(re.findall(r',\s*(\w+)\s*:\s*\w+\s*\}\)', m.group(2)))
        out.append((m.group(1).strip(), keys))
    return out


def _unconditional(src: str) -> set[str]:
    cleaned = re.sub(r'\{([^{}<>]+?) && <fieldset>.*?</fieldset>\}', '', src, flags=re.S)
    return set(re.findall(r'(?:set\w*|onChange)\(\s*\{\s*(\w+)\s*:', cleaned))


# Что обязано быть доступно у каждого вида ряда (как принято в проекте; расширять, когда вид получает новую настройку)
MUST = {
    'line': {'color', 'line', 'width', 'dash', 'marker', 'shape', 'size', 'opacity', 'valueLabels', 'label_position', 'trend', 'err_mode', 'legend_name'},
    'points': {'color', 'marker', 'shape', 'size', 'opacity', 'valueLabels', 'label_position', 'trend', 'err_mode', 'legend_name', 'hollow'},
    'bar': {'color', 'opacity', 'valueLabels', 'label_position', 'hatch', 'hatch_color', 'legend_name'},
    'box': {'color', 'opacity', 'legend_name'},
}


def _flags(kind: str) -> dict[str, bool]:
    """Значения условий из ChartSettings.SeriesLookFields и FormatPane для вида ряда (без заливки)."""
    return {
        'hasLine': kind == 'line', 'hasMarker': kind in ('line', 'points'), '!hasLine && !hasMarker': kind in ('bar', 'box'),
        "s.kind === 'bar'": kind == 'bar',
        'marker': kind in ('points', 'line'), 'labels': kind != 'box', 'trend': kind in ('points', 'line'), 'hatch': kind == 'bar',
    }


def _reach(kind: str) -> set[str]:
    flags = _flags(kind)
    base = _text('ChartSettings.tsx')
    extra = _text('FormatFields.tsx')
    out = _unconditional(base[base.index('export function SeriesLookFields'):]) | _unconditional(extra[extra.index('export function SeriesExtraFields'):])
    for src, anchor in ((base, 'export function SeriesLookFields'), (extra, 'export function SeriesExtraFields')):
        for guard, keys in _blocks(src[src.index(anchor):]):
            assert guard in flags, f'новое условие «{guard}» в окне ряда: добавьте его в _flags() этого теста'
            if flags[guard]:
                out |= keys
    if kind == 'points':
        out.add('color')                   # у точек «Цвет маркеров» пишет в color
    return out


@pytest.mark.parametrize('kind', MUST)
def test_series_kind_reaches_its_settings(kind):
    got = _reach(kind)
    missing = sorted(MUST[kind] - got)
    assert not missing, f'у ряда «{kind}» в окне «Формат» нет полей: {missing}'


def test_pane_passes_flags_per_kind():
    """FormatPane передаёт в SeriesExtraFields именно те условия, что учтены в _flags()."""
    pane = _text('FormatPane.tsx')
    for expect in ("labels={s.kind !== 'box'}", "trend={s.kind === 'points' || s.kind === 'line'}", "hatch={s.kind === 'bar'}",
                   "marker={s.kind === 'points' || (s.kind === 'line' && !s.fill)}"):
        assert expect in pane, f'FormatPane изменился: {expect}'
