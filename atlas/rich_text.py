"""Подписи с верхними и нижними индексами: ``<sup>…</sup>`` и ``<sub>…</sub>``.

Строка хранится так же, как в окне (``web/src/richText.ts``): график Plotly понимает эти теги сам,
поэтому PNG, PDF и SVG получают индексы без преобразования. Там, где индексы не выводятся
(имена файлов, листы Excel, CSV), пользуемся ``plain``.
"""
from __future__ import annotations

import re

_TAG = re.compile(r'</?(?:sup|sub)>')


def plain(text) -> str:
    """Текст без тегов индексов."""
    return _TAG.sub('', str(text or ''))


# Спецсимволы mathtext внутри ``\mathregular{…}``: подпись выводится шрифтом текста, индексы — как у Plotly.
_MATH_ESCAPE = {'\\': r'\backslash', '$': r'\$', '{': r'\{', '}': r'\}', '_': r'\_', '^': r'\^', '#': r'\#', '%': r'\%', '&': r'\&', ' ': r'\ '}


def mpl_text(text) -> str:
    """Подпись для matplotlib: индексы — mathtext, остальные HTML-теги убираются (как раньше)."""
    s = re.sub(r'<(?!/?(?:sup|sub)>)[^>]*>', '', str(text or ''))
    if not _TAG.search(s):
        return s
    out: list[str] = []
    sup = sub = False
    last = 0
    for m in _TAG.finditer(s):
        out.append(_math_piece(s[last:m.start()], sup, sub))
        on = not m.group(0).startswith('</')
        if 'sup' in m.group(0):
            sup = on
        else:
            sub = on
        last = m.end()
    out.append(_math_piece(s[last:], sup, sub))
    return '$\\mathregular{' + ''.join(out) + '}$'


def _math_piece(text: str, sup: bool, sub: bool) -> str:
    body = ''.join(_MATH_ESCAPE.get(c, c) for c in text)
    if not body:
        return ''
    if sup:
        return '^{' + body + '}'
    if sub:
        return '_{' + body + '}'
    return body
