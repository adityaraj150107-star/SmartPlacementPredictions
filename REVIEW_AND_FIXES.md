# Smart Placement Predictions — Review & Fix Log

## Fixes applied in this package

1. **Offline ML fallback:** `backend/ml_model.py` now catches `OSError` from network/download failures so the documented offline fallback dataset can be generated.
2. **Agent compatibility:** `backend/agents.py` safely falls back to the single `smart_placement` agent when a missing/legacy agent ID is sent, rather than indexing a nonexistent `general` agent and raising a server error.
3. **OTP generation:** `backend/main.py` now uses `secrets.randbelow()` for cryptographically secure six-digit OTP generation.
4. **Stale tests updated:** `backend/tests/test_main.py` now tests the current single-agent design and includes coverage for legacy/unknown agent IDs.
5. **Diagnostics:** Added `diagnose_project.py` to check required files, Python dependencies, `.env` presence/configuration status (without displaying values), and local ports.

## Checks performed in the review environment

- Python compilation: passed for project Python files.
- JavaScript syntax checks (`node --check`): passed for `app.js`, `hub.js`, and `sidebar.js`.
- ML training/evaluation/prediction smoke test using the synthetic offline fallback: passed for all four classifiers.
- Full pytest suite: **not run to completion in the review environment** because Flask, bcrypt, and slowapi are unavailable here and package installation could not reach the internet. Install `backend/requirements.txt` on the project PC and run `pytest backend` to complete the suite.

## Important notes

- The ZIP intentionally does **not** contain `backend/.env`; keep your configured local `.env` private and copy it into the extracted project if needed.
- A successful synthetic-data test does not establish real placement accuracy. For meaningful model evaluation, make sure the real placement CSV is present and validated.
- `diagnose_project.py` is a preflight check, not a replacement for browser-based end-to-end testing.

## Run on Windows / VS Code

```powershell
python -m pip install -r backend\requirements.txt
python diagnose_project.py
pytest backend
python app.py
```

Open `http://127.0.0.1:5000` in the browser. Port `8000` is the internal FastAPI backend.
