"""Сквозные цвета групп (ГСП, СП …) для всех программ: одна группа — один цвет на всех графиках и картах.

Источник правды — этот файл; Газовый Атлас получает байт-в-байт копию (tools/sync_fs_browse_to_atlas.py).

Правила:
* группы узнаются по нормированному имени (``group_key``): «ГСП-1» = «ГСП 1» = «гсп1»;
* порядок слева направо — естественный (ГСП-2 раньше ГСП-10), по номеру группы;
* палитра берётся ровно на число групп объекта (от 2 до 15 цветов, набор «Атлас-N»);
  число считается по ПОЛНОМУ списку групп объекта, а не по тем, что попали на график, иначе цвет менялся бы от графика к графику;
* решение за инженером: цвет любой группы можно задать вручную (``set_override``), выбор запоминается в ~/.pxg/group_colors.json.
"""
from __future__ import annotations

import colorsys
import json
import os
import re
from typing import Iterable, Mapping

# Набор «Атлас-N»: для каждого N свой расчёт (наибольшее наименьшее расстояние между цветами в Lab с учётом дейтеро- и протаномалии).
PALETTES: dict[int, tuple[str, ...]] = {
    2: ('#7000FF', '#00CF00'),
    3: ('#7000FF', '#00CF00', '#FF1060'),
    4: ('#00BFFF', '#FF0000', '#00CF50', '#7000FF'),
    5: ('#00BFFF', '#FF8000', '#4030FF', '#FF008F', '#00CF70'),
    6: ('#009FFF', '#AFBF00', '#7000FF', '#EF008F', '#FF0000', '#00BF9F'),
    7: ('#00BFFF', '#FF9F00', '#7000FF', '#007040', '#00CF00', '#FF50CF', '#AF2030'),
    8: ('#0040FF', '#00CF00', '#FF8F9F', '#009FEF', '#FF0000', '#00BF9F', '#606000', '#EF00BF'),
    9: ('#00AFFF', '#00CF00', '#CF0020', '#7000FF', '#00BF9F', '#8F309F', '#FF8FAF', '#606010', '#FF9F00'),
    10: ('#009FFF', '#00CF00', '#FF0000', '#FF00DF', '#00BFAF', '#407020', '#0040FF', '#9F3070', '#FF8F80', '#DFAF10'),
    11: ('#00BFFF', '#FF9F00', '#7000FF', '#00CF00', '#8F4080', '#00BF9F', '#607010', '#BF0000', '#FF8F8F', '#0070EF', '#FF10DF'),
    12: ('#0040FF', '#00CF00', '#FF0070', '#00BFFF', '#00BF9F', '#DFAF00', '#FF0000', '#5050AF', '#007010', '#AF7040', '#FF8FDF', '#FF00EF'),
    13: ('#0060CF', '#00CF00', '#FF0000', '#00BFAF', '#BF0060', '#FF10EF', '#DFAF00', '#805000', '#40BFFF', '#4030FF', '#008030', '#FF8F80', '#FF8FDF'),
    14: ('#00AFEF', '#FF8F00', '#4030FF', '#00CF70', '#BF0050', '#606000', '#0070EF', '#9FBF00', '#FF30FF', '#20BFAF', '#9F208F', '#EF8F70', '#EF8FBF', '#CF0000'),
    15: ('#0040FF', '#AFBF00', '#BF0060', '#10BFFF', '#107030', '#00BFAF', '#FF8000', '#FF10FF', '#EF8F80', '#8F309F', '#0080FF', '#EF8FCF', '#00CF60', '#FF1040', '#805000'),
}
MAX_PALETTE = max(PALETTES)
NO_GROUP = 'Без группы'
NO_GROUP_COLOR = '#8a9aa0'


def group_key(value) -> str:
    """Ключ сравнения названий групп: регистр, пробелы, «_» и «-» не различают группы («ГСП_4» = «гсп 4» = «ГСП4»)."""
    t = re.sub(r'(?<=[^\W\d_])(?=\d)', ' ', str(value).strip())
    return re.sub(r'[\s_\-]+', ' ', t).strip().casefold()


def natural_key(value) -> tuple:
    """Естественный порядок: ГСП-2 раньше ГСП-10; группы без номера — после пронумерованных, по алфавиту."""
    parts = re.split(r'(\d+)', group_key(value))
    return tuple((0, int(p)) if p.isdigit() else (1, p) for p in parts if p != '')


def sort_groups(groups: Iterable) -> list[str]:
    """Уникальные группы (по ключу) в естественном порядке; написание берётся первое встретившееся."""
    seen: dict[str, str] = {}
    for g in groups:
        s = str(g).strip()
        if s and s != 'nan':
            seen.setdefault(group_key(s), s)
    return [seen[k] for k in sorted(seen, key=natural_key)]


def palette_for(n: int) -> list[str]:
    """Палитра ровно на n цветов; свыше 15 — набор на 15 и дополнительные цвета по золотому углу."""
    if n <= 1:
        return [PALETTES[2][0]] * max(n, 0)
    if n in PALETTES:
        return list(PALETTES[n])
    base = list(PALETTES[MAX_PALETTE])
    for i in range(n - MAX_PALETTE):
        r, g, b = colorsys.hls_to_rgb((i * 0.61803398875 + 0.08) % 1, 0.46, 0.62)
        base.append('#%02x%02x%02x' % (int(r * 255), int(g * 255), int(b * 255)))
    return base


def overrides_path() -> str:
    home = os.environ.get('PXG_HOME') or os.path.join(os.path.expanduser('~'), '.pxg')
    return os.path.join(home, 'group_colors.json')


def load_overrides(path: str | None = None) -> dict[str, str]:
    """Цвета, заданные вручную: ключ группы → '#rrggbb'. Нет файла или он повреждён — пусто."""
    try:
        with open(path or overrides_path(), encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return {group_key(k): v.lower() for k, v in data.items()
            if isinstance(data, dict) and isinstance(v, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', v)}


def set_override(group, color: str | None, path: str | None = None) -> None:
    """Запомнить цвет группы (color=None — вернуть автоматический)."""
    p = path or overrides_path()
    data = load_overrides(p)
    if color is None:
        data.pop(group_key(group), None)
    else:
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
            raise ValueError(f'Цвет должен быть вида #rrggbb: {color}')
        data[group_key(group)] = color.lower()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def group_colors(all_groups: Iterable, overrides: Mapping[str, str] | None = None) -> dict[str, str]:
    """Цвета всех групп объекта: {название: '#rrggbb'}, порядок — по номеру группы.

    ``all_groups`` — полный список групп объекта. ``overrides`` по умолчанию читаются из ~/.pxg/group_colors.json.
    Цвет ищется по ключу, поэтому «ГСП 1» и «ГСП-1» получают одинаковый.
    """
    ov = load_overrides() if overrides is None else {group_key(k): v for k, v in overrides.items()}
    names = [g for g in sort_groups(all_groups) if group_key(g) != group_key(NO_GROUP)]
    palette = palette_for(len(names))
    return {g: ov.get(group_key(g), palette[i]) for i, g in enumerate(names)}


def color_of(group, colors: Mapping[str, str]) -> str:
    """Цвет группы из готовой карты (по нормированному имени); неизвестная группа и «Без группы» — нейтральный серый."""
    k = group_key(group)
    for name, c in colors.items():
        if group_key(name) == k:
            return c
    return NO_GROUP_COLOR


_known: list[str] = []


def set_known_groups(groups: Iterable) -> None:
    """Запомнить полный список групп открытого объекта: цвета графиков считаются по нему, а не по группам, попавшим на график."""
    _known[:] = sort_groups(groups)


def colors_for(names: Iterable) -> dict[str, str]:
    """Цвета для групп конкретного графика: {название: цвет}. Палитра по полному списку (``set_known_groups``) плюс эти группы."""
    names = [str(n) for n in names]
    full = group_colors([*_known, *names])
    return {n: color_of(n, full) if group_key(n) != group_key(NO_GROUP) else NO_GROUP_COLOR for n in dict.fromkeys(names)}
