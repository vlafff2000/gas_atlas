"""Страницы карточки паспорта для PDF: те же данные и те же фигуры схемы, что на экране (atlas/passport_card.py)."""
from __future__ import annotations

from typing import Any

from matplotlib import pyplot as plt
from matplotlib.patches import Rectangle

INK, MUTED, LINE, PANEL = '#1f2937', '#6b7280', '#d1d5db', '#f3f4f6'


def _fmt(value, digits=1) -> str:
    if value is None:
        return '—'
    text = f'{value:,.{digits}f}'.replace(',', ' ').replace('.', ',')
    return text


def draw_schematic(ax, sch: dict[str, Any]) -> None:
    ax.set_xlim(-3.2, 6.6)
    ax.set_ylim(sch['bottom'], sch['top'])
    ax.axis('off')
    for s in sch['shapes']:
        if s['t'] == 'rect':
            hatch = {'slots': '////', 'sand': '....'}.get(s['pattern'])
            ax.add_patch(Rectangle((s['x0'], s['y0']), s['x1'] - s['x0'], s['y1'] - s['y0'], facecolor=s['fill'],
                                   edgecolor='#0f766e' if hatch == '////' else 'none', hatch=hatch, linewidth=0))
        else:
            ax.plot([s['x0'], s['x1']], [s['y0'], s['y1']], color=s['stroke'], linewidth=s['width'] * .75, solid_capstyle='butt')
    for label in sch['labels']:
        ax.annotate(label['text'], xy=(1.0, label['y']), xytext=(3.2, label['at']), fontsize=8, color=label['color'], va='center',
                    arrowprops={'arrowstyle': '-', 'color': label['color'], 'linewidth': .6, 'shrinkA': 0, 'shrinkB': 0})
    step = max(int((sch['bottom'] - sch['top']) / 5 / 10) * 10, 5)
    y = (int(sch['top']) // step + 1) * step
    while y < sch['bottom']:
        ax.plot([-3.0, -2.8], [y, y], color=MUTED, linewidth=.6)
        ax.text(-3.05, y, f'{y:g}', fontsize=7, color=MUTED, ha='right', va='center')
        y += step
    ax.text(-3.0, sch['top'], 'м', fontsize=7, color=MUTED, ha='left', va='bottom')


def _table(ax, header: list[str], rows: list[list[str]], widths: list[float], size=7.2) -> None:
    ax.axis('off')
    if not rows:
        ax.text(0, .5, 'нет данных', fontsize=8, color=MUTED, va='center')
        return
    table = ax.table(cellText=rows, colLabels=header, colWidths=widths, loc='upper left', cellLoc='center')
    table.auto_set_font_size(False)
    table.set_fontsize(size)
    table.scale(1, 1.35)
    for (r, _), cell in table.get_celld().items():
        cell.set_edgecolor(LINE)
        cell.set_linewidth(.5)
        if r == 0:
            cell.set_facecolor(PANEL)
            cell.set_text_props(weight='bold', color=INK)


def draw_pages(card: dict[str, Any], project: str, pdf) -> None:
    """Страницы 1–2: карточка скважины. ``pdf`` — PdfPages."""
    fig = plt.figure(figsize=(8.27, 11.69))
    try:
        fig.text(.06, .965, f"Паспорт скважины № {card['well']}", fontsize=19, weight='bold', va='top', color=INK)
        sub = ' · '.join(x for x in (project, card['group'], 'конструкция на ' + card['construction_date'] if card['construction_date'] else '') if x)
        fig.text(.06, .935, sub, fontsize=9, color=MUTED, va='top')
        # Карточки показателей: 4 в ряд
        for n, k in enumerate(card['kpi']):
            col, row = n % 4, n // 4
            x, y = .06 + col * .2325, .885 - row * .075
            fig.patches.append(Rectangle((x, y - .063), .219, .068, transform=fig.transFigure, facecolor=PANEL, edgecolor=LINE, linewidth=.6))
            fig.text(x + .008, y - .005, k['label'], fontsize=6.6, color=MUTED, va='top')
            value = k.get('text') or (_fmt(k['value'], k.get('digits', 1)))
            fig.text(x + .008, y - .022, value, fontsize=13, weight='bold', color=INK, va='top')
            small = ' '.join(x for x in (k.get('unit') if k.get('value') is not None else '', k.get('hint', ''), k.get('extra', '')) if x)
            fig.text(x + .008, y - .047, small, fontsize=6.4, color=MUTED, va='top')
        sch = card['schematic']
        fig.text(.06, .715, 'Забойная часть скважины', fontsize=10.5, weight='bold', color=INK, va='top')
        if sch['items']:
            draw_schematic(fig.add_axes([.06, .395, .46, .30]), sch)
            fig.text(.06, .385, 'Показаны только эксплуатационная колонна, НКТ, фильтр, перфорация, расширка, пакер и забой. '
                     'Ширина условная, диаметры — в подписях.', fontsize=6.4, color=MUTED, va='top', wrap=True)
        else:
            fig.text(.06, .69, sch['notes'][0], fontsize=8.5, color=MUTED, va='top')
        fig.text(.55, .715, 'Сезоны эксплуатации', fontsize=10.5, weight='bold', color=INK, va='top')
        rows = [[('О' if r['kind'] == 'withdrawal' else 'З') + ' ' + r['period'], _fmt(r['volume'], 2), str(r['days']),
                 _fmt(r['max_rate'], 1), _fmt(r['mean_rate'], 1)] for r in card['seasons']][-16:]
        _table(fig.add_axes([.55, .395, .40, .30]), ['Сезон (О/З)', 'Объём,\nмлн м³', 'Дни', 'Qmax,\nтыс. м³/сут', 'Qср,\nтыс. м³/сут'],
               rows, [.27, .16, .12, .23, .22])
        fig.text(.06, .345, 'ГДИ за всё время', fontsize=10.5, weight='bold', color=INK, va='top')
        gdi = [[g['date'], g['method'][:26], _fmt(g['a'], 3), _fmt(g['b'], 4), _fmt(g['r2'], 3), _fmt(g['q_max'], 0), _fmt(g['q_free'], 0),
                'да' if g['reliable'] else 'нет'] for g in card['gdi']][-12:]
        _table(fig.add_axes([.06, .17, .89, .16]), ['Дата', 'Метод', 'a', 'b', 'R²', 'Qmax', 'Qсв', 'Надёжно'], gdi,
               [.13, .29, .09, .11, .09, .09, .09, .11])
        fig.text(.06, .155, 'Проведённые КРС', fontsize=10.5, weight='bold', color=INK, va='top')
        krs = card['krs']
        works = [[str(w['year'] or ''), w['type'], w['detail']] for w in krs['works']][-8:]
        _table(fig.add_axes([.06, .045, .89, .10]), ['Год', 'Тип ремонта', 'Подробности'], works, [.1, .35, .55])
        if krs['priority'] and krs['priority']['value'] is not None:
            p = krs['priority']
            fig.text(.95, .155, f"Приоритет КР (подсказка): {p['value']:g}" + (f" — {p['reason']}" if p['reason'] else ''), fontsize=7, color=MUTED, ha='right', va='top')
        elif krs['note']:
            fig.text(.95, .155, krs['note'], fontsize=7, color=MUTED, ha='right', va='top')
        pdf.savefig(fig)
    finally:
        plt.close(fig)
