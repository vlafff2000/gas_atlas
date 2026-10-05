"""Шрифты экспорта графиков: Times New Roman и Arial Narrow, а где их нет (Linux) — ближайшие аналоги из ``atlas/fonts``.

Аналоги: Liberation Serif (метрически совместим с Times New Roman) и Atlas Sans Narrow — Liberation Sans, сжатый до 82 %
как Arial Narrow (tools/make_narrow_font.py). Оба под SIL OFL 1.1, лежат в репозитории и попадают в портативные сборки.
Если в системе есть оригинал (Windows, Word), берётся он: SVG и PDF тогда открываются в Word с настоящим шрифтом.
"""
from __future__ import annotations

from pathlib import Path

FONT_DIR = Path(__file__).resolve().parents[2] / 'atlas' / 'fonts'
# ключ → (подпись, оригинал, запасной шрифт из репозитория)
FONTS = {
    'default': ('Стандартный (DejaVu Sans)', 'DejaVu Sans', None),
    'times': ('Times New Roman', 'Times New Roman', 'Liberation Serif'),
    'arial_narrow': ('Arial Narrow', 'Arial Narrow', 'Atlas Sans Narrow'),
}
SIZE_RANGE = (5.0, 20.0)
_registered = False


def register():
    """Подключает шрифты из ``atlas/fonts`` к Matplotlib (один раз)."""
    global _registered
    if _registered:
        return
    from matplotlib import font_manager
    for path in sorted(FONT_DIR.glob('*.ttf')):
        font_manager.fontManager.addfont(str(path))
    _registered = True


def installed(family):
    from matplotlib import font_manager
    try:
        font_manager.findfont(font_manager.FontProperties(family=family), fallback_to_default=False)
        return True
    except ValueError:
        return False


def family_for(key):
    """Имя семейства для ``font.family``: оригинал, если он установлен, иначе аналог; DejaVu — запасной для редких знаков."""
    if key not in FONTS:
        raise ValueError('Шрифт: ' + ', '.join(FONTS))
    register()
    _, original, analog = FONTS[key]
    for name in (original, analog):
        if name and installed(name):
            return [name, 'DejaVu Sans']
    return ['DejaVu Sans']


def check(font, size):
    """Проверка параметров из запроса: (ключ шрифта, размер в пт или None)."""
    font = font or 'default'
    if font not in FONTS:
        raise ValueError('Шрифт: ' + ', '.join(FONTS))
    if size in (None, ''):
        return font, None
    size = float(size)
    if not SIZE_RANGE[0] <= size <= SIZE_RANGE[1]:
        raise ValueError('Размер шрифта: от %g до %g пт' % SIZE_RANGE)
    return font, size
