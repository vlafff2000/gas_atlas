@echo off
rem Самопроверка Газового атласа на данных объекта.
rem Перетащите папку с файлами объекта (или несколько файлов) на этот файл. Результат: папка selfcheck_result рядом.
cd /d "%~dp0"
if "%~1"=="" (
  echo Перетащите папку с файлами объекта на check_data_windows.bat
  pause & exit /b 1
)
if not exist ".venv\Scripts\python.exe" (echo Сначала запустите install_windows.bat & pause & exit /b 1)
".venv\Scripts\python.exe" -X utf8 -m atlas.selfcheck %* --out "%~dp0selfcheck_result"
echo.
echo Отчёт: %~dp0selfcheck_result\selfcheck_report.md
echo Пришлите файл selfcheck_report.json в чат: по нему можно быстро разобрать результат.
if exist "%~dp0selfcheck_result\selfcheck_report.md" start "" notepad "%~dp0selfcheck_result\selfcheck_report.md"
pause
