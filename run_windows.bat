@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo Python 3.10 or newer is required.
  echo Download: https://www.python.org/downloads/windows/
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Creating virtual environment...
  py -3 -m venv .venv
)

echo [2/3] Installing required packages...
call ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo Installation failed.
  pause
  exit /b 1
)

echo [3/3] Starting FrameDrop...
start "" ".venv\Scripts\pythonw.exe" frame_exporter.py
endlocal
