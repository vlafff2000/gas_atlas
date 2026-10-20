# Передача: конструктор графиков, этап 2 — окна настройки (до 15 строк)

- **Цель раздела:** свой график из любых полей проекта (план и решения Egor — `chart-builder/plan.md`, этапы 1–5).
- **Сделано:** этап 1 — каркас (каталог полей, ряды с ключом связи, оси Y1–Y5). Этап 2 — окна «Ряд», «Ось», «График» (линии, маркеры, цвета, границы, шаг,
  логарифм, форматы чисел и дат, шрифты, легенда, сетка, фон); пусто — авто; предпросмотр сразу; PNG/SVG/PDF/XLSX как на экране.
- **Файлы этапа 2:** `atlas/chart_style.py` (разбор и проверка), `atlas/engine/core/export_style.py` (статический рендер), `atlas/render.py`, `atlas/contract.py`
  (`Series.look`, `Axis.style`, `Chart.style`), `atlas/modules/builder.py`, `web/src/BuilderDialogs.tsx`, `ChartBuilder.tsx`, `ChartSettings.tsx` (`SeriesLookFields`),
  `ChartView.tsx`, `tests/atlas/test_builder.py`, `test_builder_export.py`.
- **Решения:** макет `layout` расширен без смены версии: `series[].look`, `axis_style`, `chart_style`; заданный цвет ряда общий для всех его кривых (скважин).
- **Открытые вопросы:** XLSX берёт только цвет ряда (толщина и маркеры — нет); отдельной выгрузки Word для одного графика нет (отчёты — этап 5);
  размер шрифта на экране в px, в файле в пт (одно число); заданный шаг при нескольких осях Y отключает выравнивание делений.
- **Следующий шаг:** этап 3 — комбинированные типы на одной оси (линия, точки, столбцы, область, ступенчатая, стопка).
- **Проверка:** `python -m pytest -q tests/atlas/test_builder.py tests/atlas/test_builder_export.py`; `cd web && npx tsc --noEmit && npm run build`
