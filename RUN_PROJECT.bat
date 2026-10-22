@echo off
cd /d "%~dp0"
echo ===============================================
echo Smart Placement Predictions AI Agent
echo ===============================================
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.11 or 3.12 and enable Add Python to PATH.
  pause
  exit /b 1
)
python app.py
pause
