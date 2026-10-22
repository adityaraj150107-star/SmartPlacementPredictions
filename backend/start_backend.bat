@echo off
rem Only needed if you want to run the FastAPI backend on its own
rem (python app.py, from the project root, already starts it automatically).
setlocal
set "ROOT=%~dp0.."
cd /d "%ROOT%"
python -m uvicorn backend.main:app --port 8000
pause
