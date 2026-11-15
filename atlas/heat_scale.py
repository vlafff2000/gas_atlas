"""Цветовые шкалы тепловой карты: одна таблица опорных цветов для экрана (``web/src/heatScale.ts``, зеркало) и для файла.

Схема задаётся в оформлении графика (``heat_scale``), её можно развернуть (``heat_reverse``). Цвет текста в ячейке выбирается по яркости
фона, а не по доле от максимума, чтобы подпись читалась на любой схеме."""
from __future__ import annotations

SCALES = ('orange', 'blue', 'green', 'redgreen', 'gray')
LABELS = {'orange': 'Оранжевая', 'blue': 'Синяя', 'green': 'Зелёная', 'redgreen': 'Зелёная к красной', 'gray': 'Серая (для чёрно-белой печати)'}
STOPS = {
    'orange': [(255, 247, 236), (253, 212, 158), (252, 141, 89), (215, 48, 31), (127, 0, 0)],
    'blue': [(247, 251, 255), (198, 219, 239), (107, 174, 214), (33, 113, 181), (8, 48, 107)],
    'green': [(247, 252, 245), (199, 233, 192), (116, 196, 118), (35, 139, 69), (0, 68, 27)],
    'redgreen': [(26, 152, 80), (166, 217, 106), (255, 255, 191), (253, 174, 97), (215, 48, 39)],
    'gray': [(255, 255, 255), (217, 217, 217), (150, 150, 150), (82, 82, 82), (0, 0, 0)],
}
DARK_LUMA = 150


def color(t: float, scheme: str = 'orange', reverse: bool = False) -> tuple[int, int, int]:
    """Цвет шкалы в точке ``t`` от 0 до 1."""
    stops = STOPS.get(scheme or 'orange', STOPS['orange'])
    t = min(1.0, max(0.0, float(t)))
    x = (1 - t if reverse else t) * (len(stops) - 1)
    i = min(len(stops) - 2, int(x))
    f = x - i
    return tuple(round(a + (b - a) * f) for a, b in zip(stops[i], stops[i + 1]))     # type: ignore[return-value]


def is_dark(rgb: tuple[int, int, int]) -> bool:
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2] < DARK_LUMA


def colormap(scheme: str = 'orange', reverse: bool = False):
    from matplotlib.colors import LinearSegmentedColormap
    return LinearSegmentedColormap.from_list('heat', [tuple(c / 255 for c in color(i / 4, scheme, reverse)) for i in range(5)])
