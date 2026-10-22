import importlib
import sys
from pathlib import Path

import pytest

# Make sure `backend` is importable as a package when tests are run from
# anywhere (e.g. `pytest` from the project root, or from inside backend/).
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    """Spins up the FastAPI app against a completely isolated SQLite database,
    a temp-directory ML dataset/model, and with SMTP/OAuth disabled -- so the
    test suite never touches real infrastructure or the developer's own DB."""
    monkeypatch.setenv('ADMIN_EMAIL', 'admin@test.local')
    monkeypatch.setenv('ADMIN_PASSWORD', 'TestAdminPass123!')
    monkeypatch.setenv('FLASK_SECRET_KEY', 'test-secret-key-not-for-real-use')
    monkeypatch.setenv('BACKEND_SESSION_SECRET', 'test-backend-secret-not-for-real-use')
    monkeypatch.setenv('SESSION_TTL_DAYS', '7')
    monkeypatch.setenv('MAX_OTP_ATTEMPTS', '3')
    monkeypatch.setenv('LLM_PROVIDER', 'auto')

    import backend.database as database
    importlib.reload(database)
    database.DB = tmp_path / 'test_placement.db'

    import backend.ml_model as ml_model
    importlib.reload(ml_model)
    ml_model.DATA = tmp_path / 'data' / 'Placement_Data_Full_Class.csv'
    ml_model.MODEL = tmp_path / 'models' / 'placement_rf.joblib'
    ml_model.METRICS = tmp_path / 'models' / 'metrics.json'

    import backend.main as main
    importlib.reload(main)  # re-runs init_db() etc. against the patched paths above

    monkeypatch.setattr(main, 'UPLOAD_DIR', tmp_path / 'uploads')

    # Never send real emails in tests -- capture what *would* have been sent
    # so tests can read the OTP back out instead of needing a real inbox.
    sent = {}

    def fake_send_email(to, subject, body):
        sent['to'] = to
        sent['subject'] = subject
        sent['body'] = body

    monkeypatch.setattr(main, 'send_email', fake_send_email)

    from fastapi.testclient import TestClient
    client = TestClient(main.app)
    yield client, main, database, ml_model, sent
