@echo off
rem Газовый атлас 6 (предварительная версия). Нужен Python 3.8+ в .venv (install_windows.bat).
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (echo Run install_windows.bat first. & pause & exit /b 1)
".venv\Scripts\python.exe" -c "import starlette, uvicorn, webview" 2>nul || ".venv\Scripts\python.exe" -m pip install -r requirements-atlas.txt || (pause & exit /b 1)
".venv\Scripts\python.exe" -m atlas %*
