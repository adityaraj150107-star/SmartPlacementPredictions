@echo off
rem Double-click this from inside the backend\ folder. It runs the project's
rem app.py, which lives one folder up (the project root).
setlocal
set "ROOT=%~dp0.."
cd /d "%ROOT%"
set "PY=python"
if exist "%ROOT%\venv\Scripts\python.exe" set "PY=%ROOT%\venv\Scripts\python.exe"

echo ==============================================
echo   Smart Placement Predictions
echo ==============================================
echo One window starts everything: Ollama (if installed), backend and website.
echo.
"%PY%" app.py
pause
