@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"
set "PYTHON="

where py >nul 2>nul
if not errorlevel 1 (
  py -3 check_gui_dependencies.py >nul 2>nul
  if not errorlevel 1 set "PYTHON=py -3"
)

if "%PYTHON%"=="" (
  where python >nul 2>nul
  if not errorlevel 1 (
    python check_gui_dependencies.py >nul 2>nul
    if not errorlevel 1 set "PYTHON=python"
  )
)

if "%PYTHON%"=="" (
  echo No Python runtime with the required GUI dependencies was found.
  echo.
  echo Tried: py -3 and python.
  echo Install dependencies from this folder with:
  echo   python -m pip install -r requirements.txt
  pause
  exit /b 1
)

%PYTHON% check_gui_dependencies.py
if errorlevel 1 (
  pause
  exit /b 1
)

%PYTHON% gui_app.py
endlocal
