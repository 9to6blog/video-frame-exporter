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

if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv
call ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :failed

rem PyInstaller 6.12 needs this explicit import with NumPy 2.3 and newer.
call ".venv\Scripts\pyinstaller.exe" --noconfirm --clean --onefile --windowed --name FrameDrop --collect-all cv2 --hidden-import numpy._core._exceptions frame_exporter.py
if errorlevel 1 goto :failed

echo.
echo Build complete: dist\FrameDrop.exe
pause
exit /b 0

:failed
echo.
echo Build failed.
pause
exit /b 1
