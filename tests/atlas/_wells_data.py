"""Демонстрационный объект с суточной эксплуатацией, контролем воды, забоем и конструкцией (для анализа скважин)."""
import numpy as np
import pandas as pd

from app.core.demo import demo_frames


def well_frames():
    frames = demo_frames()
    prod = frames['production']
    rng = np.random.default_rng(7)
    p = prod[prod.well.isin(['31', '45'])].reset_index(drop=True)
    ops = p[['well', 'date', 'kind']].copy()
    n = len(ops)
    ops['work_hours'] = rng.choice([24.0, 20.0, 12.0, 0.0, np.nan], n, p=[.6, .15, .1, .05, .1])
    ops['gas_volume_m3'] = np.where(rng.random(n) < .2, np.nan, p.q.to_numpy(float) * 1000 * rng.uniform(.9, 1.1, n))
    ops['water_volume_m3'] = np.where(rng.random(n) < .9, np.nan, rng.uniform(0, 3, n).round(2))
    ops['water_flag'] = rng.choice(['Да', 'Нет', 'Неизвестно'], n, p=[.05, .15, .8])
    ops['p_res'] = rng.uniform(95, 110, n).round(2)
    ops['p_bh'] = (ops.p_res - rng.uniform(3, 12, n)).round(2)
    ops['p_wellhead'] = (ops.p_bh - 10).round(2)
    ops['p_line'] = np.where(rng.random(n) < .5, np.nan, (ops.p_wellhead - 5).round(2))
    ops['temperature'] = np.nan
    ops['comment'] = ''
    water_dates = pd.date_range('2023-12-01', '2026-03-01', freq='MS')
    water = pd.DataFrame({'well': '31', 'date': water_dates,
                          'water_rate': [0.0 if i % 3 else 1.5 for i in range(len(water_dates))],
                          'water_flag': ['Да' if i % 3 == 0 else 'Нет' for i in range(len(water_dates))]})
    bottom = pd.DataFrame({'well': ['31', '31', '31', '45'],
                           'date': pd.to_datetime(['2023-06-01', '2024-06-01', '2025-06-01', '2025-06-01']),
                           'bottom_m': [1000.0, 996.5, 985.0, 1200.0], 'tool_diameter_mm': [118.0, 118.0, np.nan, 118.0],
                           'comment': ['', 'очистка', '', '']})
    construction = pd.DataFrame({
        'well': '31', 'date': pd.Timestamp('2020-01-01'),
        'element': ['Эксплуатационная колонна', 'НКТ', 'Интервал перфорации'],
        'top_m': [0.0, 0.0, 960.0], 'bottom_m': [1010.0, 940.0, 995.0], 'diameter_mm': [168.0, 73.0, np.nan],
        'inner_diameter_mm': [150.0, 62.0, np.nan]})
    frames.update(operations=ops, water=water, bottom=bottom, construction=construction)
    return frames


def make_project(projects):
    pid = projects.create_demo()
    projects.store.commit(pid, frames=well_frames(), action='Тестовые данные скважин')
    return pid
