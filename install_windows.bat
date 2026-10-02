@echo off
cd /d "%~dp0"
rem Any 64-bit CPython 3.8 or newer. Set PYTHON_BIN to choose one explicitly.
if defined PYTHON_BIN (set "ATLAS_PY=%PYTHON_BIN%") else (set "ATLAS_PY=py -3")
%ATLAS_PY% tools\install.py
if errorlevel 1 (echo Installation failed. & pause & exit /b 1)
pause
