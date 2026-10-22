"""Safe local preflight checks for Smart Placement Predictions.

Run from the project root with: python diagnose_project.py
This script never prints .env values or API keys.
"""
from __future__ import annotations

import importlib.util
import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / 'backend'
ENV_FILE = BACKEND / '.env'

REQUIRED_MODULES = {
    'flask': 'Flask frontend',
    'fastapi': 'FastAPI backend',
    'uvicorn': 'Backend server',
    'requests': 'Frontend-to-backend requests',
    'dotenv': 'Environment configuration',
    'pydantic': 'API validation',
    'multipart': 'File uploads',
    'pypdf': 'PDF resume parsing',
    'pandas': 'Dataset processing',
    'sklearn': 'Machine learning',
    'joblib': 'Model persistence',
    'bcrypt': 'Password hashing',
    'slowapi': 'API rate limiting',
    'pytest': 'Automated tests',
    'httpx': 'API test client',
}

PLACEHOLDER_VALUES = {
    '', 'replace-with-a-long-random-secret', 'yourgmail@gmail.com',
    'your_16_character_app_password', 'your_password', '...',
}


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding='utf-8', errors='replace').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.25):
            return True
    except OSError:
        return False


def main() -> int:
    errors = 0
    print('Smart Placement Predictions — local diagnostics')
    print(f'Project root: {ROOT}')
    print(f'Python: {sys.version.split()[0]}')
    print('\n[Required files]')
    for rel in ('app.py', 'frontend/app.py', 'frontend/templates/login.html',
                'frontend/templates/dashboard.html', 'backend/main.py',
                'backend/database.py', 'backend/ml_model.py',
                'backend/requirements.txt'):
        ok = (ROOT / rel).is_file()
        print(f'{"OK" if ok else "MISSING"}: {rel}')
        errors += not ok

    print('\n[Python dependencies]')
    for module, purpose in REQUIRED_MODULES.items():
        try:
            ok = importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            ok = False
        print(f'{"OK" if ok else "MISSING"}: {module} — {purpose}')
        errors += not ok

    print('\n[Environment file]')
    env = read_env(ENV_FILE)
    if not ENV_FILE.is_file():
        print('MISSING: backend/.env (copy backend/.env.example and configure it)')
        errors += 1
    else:
        print('OK: backend/.env exists (values hidden)')
        for key in ('FLASK_SECRET_KEY', 'ADMIN_EMAIL', 'ADMIN_PASSWORD', 'BACKEND_URL'):
            value = env.get(key, '')
            ok = bool(value) and value.lower() not in PLACEHOLDER_VALUES
            print(f'{"OK" if ok else "CHECK"}: {key} ' + ('is set' if ok else 'is empty or still a placeholder'))
            if not ok:
                errors += 1
        smtp_keys = ('SMTP_HOST', 'SMTP_USERNAME', 'SMTP_PASSWORD', 'SMTP_FROM')
        smtp_ready = all(env.get(k, '').strip() and env.get(k, '').strip().lower() not in PLACEHOLDER_VALUES for k in smtp_keys)
        gemini_ready = bool(env.get('GEMINI_API_KEY', '').strip()) and not env.get('GEMINI_API_KEY', '').strip().lower().startswith('your_')
        print(f'{"OK" if smtp_ready else "OPTIONAL/CHECK"}: SMTP settings ' + ('appear configured' if smtp_ready else 'not fully configured; email OTP will not work until configured'))
        print(f'{"OK" if gemini_ready else "OPTIONAL"}: Gemini API key ' + ('appears configured' if gemini_ready else 'not detected; local Ollama must be available for text AI'))

    print('\n[Local ports]')
    for port in (5000, 8000):
        state = 'IN USE (server may already be running)' if port_open(port) else 'free'
        print(f'{port}: {state}')

    print('\nThis is a preflight check, not a full end-to-end test. Run `pytest backend` after installing requirements.')
    if errors:
        print(f'\nResult: {errors} required check(s) need attention.')
        return 1
    print('\nResult: required preflight checks passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
