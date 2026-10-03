# Газовый атлас 6: каркас

Решение и причины — в [ADR-001](adr/ADR-001-architecture.md). Здесь — как запускать и как подключать модули.

## Запуск

Windows: `run_atlas_windows.bat` (нужен Python 3.10+ в `.venv`; недостающие пакеты из
`requirements-atlas.txt` поставятся сами). Открывается окно приложения (pywebview).
Linux: `bash run_atlas.sh` — то же в браузере.

Вручную: `python -m atlas` (окно), `python -m atlas --browser`, `python -m atlas --server` (только ядро на порту 8765).

Проекты общие с версией 5.8: та же папка `storage/`. Данные пока загружаются в 5.8 (`run_windows.bat`),
затем открываются в 6. Для пробы без своих данных в 6 есть кнопка «Открыть демонстрационный объект».

## Устройство

```
atlas/
  contract.py   контракт модуля: ModuleSpec, Param, Result (Table, Chart, Note)
  domain.py     словарь ПХГ: фонд скважин, виды наборов данных, колонки, единицы
  registry.py   находит модули в atlas/modules/ сам
  projects.py   проекты: адаптер к app/core/storage.py, кэш данных в памяти, исключённые точки
  api.py        HTTP/JSON (Starlette), раздаёт и собранный интерфейс
  __main__.py   запуск: сервер + окно
  modules/      по файлу на модуль: gdi.py, production.py, histograms.py (общее — _production.py)
  web/dist/     собранный интерфейс (в git, чтобы пользователю не нужен был Node)
web/            исходники интерфейса: React + TypeScript + ECharts
tests/atlas/    тесты ядра; паритет ГДИ с 5.8 — побитовый
```

API:

| Запрос | Что делает |
|---|---|
| `GET /api/modules` | описания всех модулей (`spec`) — из них интерфейс строит навигацию и панели |
| `GET /api/projects` | список проектов |
| `POST /api/projects/demo` | создать демонстрационный объект |
| `GET /api/projects/{id}/options?dataset=gdi&column=well` | варианты для списков выбора |
| `POST /api/modules/{id}/run` `{project, params}` | расчёт, ответ — `Result` в JSON |
| `POST /api/modules/{id}/export` `{project, params, target, id, format, dpi}` | график (SVG/PDF/PNG) или таблицы (XLSX, одна таблица — CSV) |
| `GET /api/projects/{id}` | сводка проекта: ревизия, наборы данных, общие настройки, число исключений |
| `PATCH /api/projects/{id}/settings` `{values}` | общие настройки проекта (пока `r2_threshold`) |
| `POST /api/projects/{id}/exclusions` `{dataset, add, remove, reason}` | исключить / вернуть точки (журнал как в 5.8) |
| `POST /api/projects/{id}/exclusions/undo` | отменить последнее исключение |
| `POST /api/projects/{id}/exclusions/state` `{at, side, revision}` | «История фильтра»: восстановить состояние до / после изменения (`atlas/api_exclusions.py`) |
| `GET/POST /api/projects/{id}/state/{module}?panel=N` | сохранённый вид панели и «Расчет …» в истории (формат 5.8) |
| `POST /api/modules/{id}/options` `{project, param, params}` | варианты зависимого списка |

Ошибки приходят как `{"error": "текст для пользователя"}`: 400 — неверный параметр,
404 — нет проекта или модуля, 409 — в проекте нет нужных данных, 500 — сбой модуля (подробности в журнале).

## Как подключить скрипт

Создайте файл `atlas/modules/<имя>.py`. Интерфейс и API менять не нужно.

```python
from atlas.contract import Module, ModuleSpec, Param, Option, Source, Result, Table, Chart, Axis, Series, Note
from atlas.domain import DatasetKind

class WaterControl(Module):
    spec = ModuleSpec(
        id='water', title='Контроль воды', group='Эксплуатация',
        needs=(DatasetKind.WATER,),
        params=(
            Param('wells', 'Скважины', 'multi', default=[], source=Source(DatasetKind.WATER, 'well')),
            Param('limit', 'Порог воды', 'number', default=1.0, minimum=0, unit='м³/сут'),
        ),
    )

    def run(self, data, params):
        d = data[DatasetKind.WATER]
        if params['wells']:
            d = d[d.well.isin(params['wells'])]
        # ... расчёт: здесь вызывается существующая функция скрипта
        return Result(tables=[Table('rows', 'Замеры', d)])
```

Правила:

1. `run` — чистая функция: не пишет файлы, не держит состояние, не меняет входные таблицы.
2. Проверенная математика вызывается как есть; новый код — только выбор данных и представление.
3. Для перенесённого раздела — чек-лист функций в `docs/parity/<раздел>.md` и тест паритета со старыми функциями
   (пример: `docs/parity/gdi.md`, `tests/atlas/test_gdi_module.py`). Раздел готов, когда закрыт весь чек-лист.
4. Тексты для пользователя — по-русски, в заметках (`Note`) объясняется, что делать, а не только что случилось.
5. Пустая выборка — заметка, а не исключение.

Виды параметров: `number`, `integer`, `boolean`, `choice` (варианты в `options`), `multi`
(варианты в `options` или из данных через `source`), `date` (ISO-дата, пусто — без границы). Пустой `multi` по соглашению означает «все».
`section` группирует параметры на панели; `setting` привязывает параметр к общей настройке проекта.

Что модуль может вернуть, кроме таблиц и графиков:
- точки графика с `ids` и `dataset` — щелчок в режиме «Исключать точки кликом» исключает точку;
- `Table.action` — флажки в строках и кнопка применения (ручной фильтр, подтверждение выбросов);
- `Table.note`, `Table.collapsed`, `Note` — пояснения и свёрнутые таблицы;
- столбцы (`Series.kind='bar'`, ось `scale='category'`), ящики с усами (`Series.kind='box'`: y — пять чисел на категорию),
  заданные границы оси (`Axis.minimum` / `maximum`), подсказка на каждую точку (`Series.labels`), штрихи и толщина линий.

Зависимые списки: `Param(dynamic=True, depends=('kind',), auto='last:3')` и метод `Module.options(name, data, params)` —
интерфейс спрашивает варианты у модуля при смене параметров, из которых они зависят, отбрасывает недопустимое
и подставляет выбор по умолчанию (`'all'`, `'first:10'`, `'last:3'`). `Param.show_if` скрывает параметр в других режимах.
`ModuleSpec.panels=2` включает «две независимые панели»; ключ сохранённого вида на панель задаёт `Module.panel_key`.

`data[kind]` — данные без исключённых точек, `data.raw[kind]` — все исходные (с `_point_id`),
`data.excluded` — журнал исключений.

## Разработка интерфейса

```
python -m atlas --server        # ядро на 8765
cd web && npm install && npm run dev   # http://localhost:5173, /api проксируется в ядро
npm run build                   # пересобрать atlas/web/dist перед коммитом
```

CI проверяет, что `atlas/web/dist` соответствует исходникам.

## Что дальше (по ADR)

Импорт данных в 6 (перенос `app/core/storage.py` и `loader.py` за API), экспорт `Result` в Excel/PNG
одной функцией для всех модулей, исключение точек кликом, затем остальные страницы 5.8 и ваши скрипты.
