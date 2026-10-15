# Переносная сборка (без установки и без интернета)

Для компьютеров, где нельзя ставить Python и библиотеки. Архив содержит свой Python 3.13, все пакеты
из `requirements-lock-py313.txt` и обе версии атласа. Пользователь распаковывает архив и запускает файл.

| Архив | Python внутри | Где работает | Запуск |
|---|---|---|---|
| `Gas_Atlas_portable_windows_x64.zip` | CPython 3.13.16 с python.org (пакет nuget.org, подпись PSF) | Windows 10 – 11, 64-bit | `Gas_Atlas_6.bat`, `Sozdat_yarlyki.bat` (ярлыки со значками на рабочий стол) |
| `Gas_Atlas_portable_linux_x64.tar.gz` | CPython 3.13.16 (python-build-standalone, самый новый символ glibc в сборке — 2.17) | Linux x86_64 с glibc 2.17+: РЕД ОС 7.3 и новее, Astra, ALT, CentOS 7+ | `gas_atlas_6.sh`, `sozdat_yarlyki.sh` |

Архив весит около 175 МБ, в распакованном виде около 700 МБ. Данные (`storage/`) хранятся рядом
с программой; при обновлении папку `storage` переносят в новую распаковку. Можно задать другую папку
переменной `GAS_ATLAS_STORAGE`.

На Windows атлас 6 открывается в окне (Edge WebView2). Если WebView2 нет,
атлас открывается в браузере. На Linux атлас всегда открывается в браузере.

## Сборка

Нужны интернет и любой Python 3.12+ с pip, на любой ОС:

    python tools/build_portable.py windows   # -> dist/Gas_Atlas_portable_windows_x64.zip
    python tools/build_portable.py linux     # -> dist/Gas_Atlas_portable_linux_x64.tar.gz

Скрипт скачивает Python (с проверкой sha256), ставит в него готовые колёса для целевой платформы
(на Linux только manylinux2014, glibc 2.17), копирует приложение и кладёт файлы запуска. Если
сборка идёт на целевой ОС, в конце скрипт проверяет импорт обоих приложений встроенным Python.
Архивы CI собирает только по запросу: GitHub → Actions → «Portable archives» → Run workflow (или пуш тега `v*`).
Workflow запускает из распакованного архива Атлас 6 и выкладывает архивы в артефакты запуска.
Обычный CI (`ci.yml`) идёт на Python 3.13; 3.12 и 3.13 сразу — Actions → CI → Run workflow → `all_pythons`.
Правки только в `docs/`, `*.md` и `storage/` CI не запускают.

Новый пакет в `requirements-lock-py313.txt` должен иметь колёсо `cp313` (или `py3-none-any`) под
`win_amd64` и `manylinux2014_x86_64`. Чистый Python, опубликованный только исходниками, допишите
в `SDIST_ONLY` в `tools/build_portable.py`.
