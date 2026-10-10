@echo off
rem Gas Atlas self-check on object data. Drag the object folder (or files) onto this file.
cd /d "%~dp0"
if "%~1"=="" (
  echo Drag the folder with object files onto check_data_windows.bat
  pause & exit /b 1
)
if not exist ".venv\Scripts\python.exe" (echo Run install_windows.bat first & pause & exit /b 1)
".venv\Scripts\python.exe" -X utf8 -m atlas.selfcheck %* --out "%~dp0selfcheck_result"
echo.
echo Report: %~dp0selfcheck_result\selfcheck_report.md
echo Send selfcheck_report.json to the chat for analysis.
if exist "%~dp0selfcheck_result\selfcheck_report.md" start "" notepad "%~dp0selfcheck_result\selfcheck_report.md"
pause
