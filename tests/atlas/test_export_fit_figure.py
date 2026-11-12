"""Пакетные вкладки «Экспорта» (фигуры кода 5.8): шкалы Y в файлах подбирает та же функция, что на экране разделов
и в интерактивном предпросмотре (atlas/axis_auto.py)."""
from __future__ import annotations

import plotly.graph_objects as go

from atlas import chart_labels
from atlas.axis_auto import auto_chart
from atlas.engine.core.reporting import FigureJob, ReportPlan
from atlas.export_chart import fit_figure, to_chart


def _figure(**layout):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[1, 2, 3, 4], y=[583.3, 760.0, 905.5, 1085.6], name='сезон 1', mode='lines'))
    fig.add_trace(go.Scatter(x=[1, 2, 3, 4], y=[0.31, 0.5, 0.7, 0.97], name='давление', mode='lines', yaxis='y2'))
    fig.update_layout(yaxis2={'overlaying': 'y', 'side': 'right'}, **layout)
    return fig


def _axes(fig):
    return [(a.range[0], a.range[1], a.dtick) if a.range is not None else None for a in (fig.layout.yaxis, fig.layout.yaxis2)]


def test_batch_file_axes_equal_interactive_preview():
    """Файл пакетной вкладки и интерактивный предпросмотр того же графика получают одни границы и шаг."""
    plan = chart_labels.labelled(ReportPlan([FigureJob('Отбор · 1', _figure, {}, 'production')], {}), {})
    job = plan.jobs[0]
    shown = auto_chart(to_chart(job.render(fit=False)))
    assert _axes(job.render()) == [(shown.axis_at(n).minimum, shown.axis_at(n).maximum, shown.axis_at(n).step) for n in ('y', 'y2')]
    assert _axes(job.render(fit=False)) == [None, None]         # интерактивному предпросмотру фигура отдаётся без подбора: он делает его сам


def test_fit_is_same_after_second_pass():
    once = _axes(fit_figure(_figure()))
    assert _axes(fit_figure(fit_figure(_figure()))) == once
    counts = {round((hi - lo) / step) for lo, hi, step in once}
    assert len(counts) == 1 and 4 <= counts.pop() <= 8          # число делений одно на обе шкалы


def test_manual_bounds_from_format_are_left_to_the_engineer():
    fig = _figure(meta={'format': {'axes': {'y': {'min': 100.0}}}})
    fit_figure(fig)
    assert fig.layout.yaxis.range is None                        # ручную шкалу рисует оформление, подбор её не трогает
    assert fig.layout.yaxis2.range is not None


def test_hidden_series_do_not_stretch_the_axis():
    fig = _figure()
    fig.add_trace(go.Scatter(x=[1, 2], y=[5000.0, 9000.0], name='скрытый', visible=False))
    assert _axes(fit_figure(fig)) == _axes(fit_figure(_figure()))


def test_level_line_outside_fit_keeps_old_axis():
    fig = _figure()
    fig.add_hline(y=2500.0)
    fit_figure(fig)
    assert fig.layout.yaxis.range is None and fig.layout.yaxis2.range is not None


def test_figure_that_series_cannot_describe_is_not_touched():
    for extra in (go.Box(y=[1.0, 2.0, 30.0], name='ящик'),
                  go.Scatter(x=[1, 2], y=[10.0, 20.0], error_y={'array': [500.0, 500.0]}, name='с планками'),
                  go.Scatter(x=[1, 2], y=[10.0, 20.0], stackgroup='s', name='стопка')):
        fig = _figure()
        fig.add_trace(extra)
        assert _axes(fit_figure(fig)) == [None, None]


def test_png_is_drawn_with_fitted_ticks():
    """В готовом рисунке деления те же: проверяем по осям Matplotlib."""
    import matplotlib.pyplot as plt
    from atlas.engine.core import export
    seen = {}
    real = plt.close

    def keep(f=None):
        if f is not None and hasattr(f, 'axes') and f.axes:
            seen['y'] = [round(float(v), 6) for v in f.axes[0].get_yticks()]
            seen['lim'] = f.axes[0].get_ylim()
        return real(f)
    plt.close = keep
    try:
        fig = fit_figure(_figure())
        export.figure_bytes(fig, 'png', 150, 160)
    finally:
        plt.close = real
    lo, hi, step = _axes(fig)[0]
    assert seen['lim'] == (lo, hi)
    assert seen['y'] == [round(lo + i * step, 6) for i in range(round((hi - lo) / step) + 1)]
