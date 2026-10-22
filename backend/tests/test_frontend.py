"""Tests for the Flask frontend (CSRF, login proxy, hub page).
The backend is mocked, so these run without FastAPI, Ollama or the internet."""
import os, sys, re
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault('FLASK_SECRET_KEY', 'test-secret-key-not-for-real-use')

from frontend.app import app  # noqa: E402

app.config['TESTING'] = True


class FakeResp:
    def __init__(self, body, status=200, headers=None, content=b''):
        self._body, self.status_code, self.headers, self.content = body, status, headers or {}, content
        self.ok = status < 400

    def json(self):
        return self._body


def _csrf(client):
    html = client.get('/').get_data(as_text=True)
    return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)


def test_login_page_is_simple_email_password_only():
    html = app.test_client().get('/').get_data(as_text=True)
    assert 'id="email"' in html and 'id="password"' in html
    assert 'Apple' not in html and 'google' not in html.lower()


def test_register_page_has_no_google_button():
    assert 'google' not in app.test_client().get('/register').get_data(as_text=True).lower()


def test_api_post_without_csrf_is_rejected():
    r = app.test_client().post('/api/login', json={'email': 'a@b.co', 'password': 'x'})
    assert r.status_code == 403


def test_login_stores_token_server_side_and_never_returns_it():
    c = app.test_client()
    token = _csrf(c)
    fake = FakeResp({'token': 'SECRET-SESSION', 'user': {'id': 1, 'name': 'A', 'email': 'a@b.co', 'role': 'student'}})
    with mock.patch('frontend.app.requests.post', return_value=fake):
        r = c.post('/api/login', json={'email': 'a@b.co', 'password': 'x'}, headers={'X-CSRF-Token': token})
    assert r.status_code == 200
    assert 'SECRET-SESSION' not in r.get_data(as_text=True)
    with c.session_transaction() as s:
        assert s['token'] == 'SECRET-SESSION'


def test_dashboard_requires_login_then_shows_agent_hub():
    c = app.test_client()
    assert c.get('/dashboard').status_code == 302
    with c.session_transaction() as s:
        s['token'] = 't'; s['user'] = {'id': 1, 'name': 'Asha', 'email': 'a@b.co', 'role': 'student'}
    html = c.get('/dashboard').get_data(as_text=True)
    for needle in ['id="hub"', 'Add photos &amp; files', 'Add from library', 'Create image', 'Sketch',
                   'Web search', 'Deep research', 'Visualize', 'hub.js', 'viewport-fit=cover']:
        assert needle in html, needle


def test_no_google_routes_exist():
    c = app.test_client()
    assert c.get('/auth/google/login').status_code == 404
    assert c.get('/auth/google/callback').status_code == 404


def test_files_endpoint_requires_login():
    assert app.test_client().get('/api/files/1').status_code == 401


def test_file_proxy_passes_bytes_and_type():
    c = app.test_client()
    with c.session_transaction() as s:
        s['token'] = 't'
    fake = FakeResp({}, 200, {'Content-Type': 'image/png', 'Content-Disposition': 'inline; filename="a.png"'}, b'PNGDATA')
    with mock.patch('frontend.app.requests.get', return_value=fake):
        r = c.get('/api/files/7')
    assert r.status_code == 200 and r.data == b'PNGDATA' and r.mimetype == 'image/png'


def test_expired_backend_session_logs_the_browser_out():
    c = app.test_client()
    token = _csrf(c)
    with c.session_transaction() as s:
        s['token'] = 'old'; s['user'] = {'role': 'student'}
    with mock.patch('frontend.app.requests.request', return_value=FakeResp({'detail': 'expired'}, 401)):
        r = c.post('/api/agent/chat', json={'message': 'hi'}, headers={'X-CSRF-Token': token})
    assert r.status_code == 401
    with c.session_transaction() as s:
        assert 'token' not in s


def test_backend_down_gives_readable_error():
    import requests
    c = app.test_client()
    token = _csrf(c)
    with c.session_transaction() as s:
        s['token'] = 't'
    with mock.patch('frontend.app.requests.request', side_effect=requests.ConnectionError('refused')):
        r = c.post('/api/agent/chat', json={'message': 'hi'}, headers={'X-CSRF-Token': token})
    assert r.status_code == 503 and 'Backend connection failed' in r.get_json()['detail']
