import os, sys, secrets, socket, shutil, subprocess, atexit, time
from urllib.parse import urlparse
from flask import Flask, render_template, request, jsonify, session, redirect, Response
import requests
from threading import Timer
from pathlib import Path
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
load_dotenv(ROOT / 'backend' / '.env')

app = Flask(__name__, template_folder=str(BASE / 'templates'), static_folder=str(BASE / 'static'))
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # uploads (backend enforces 8 MB per file)

FLASK_ENV = os.getenv('FLASK_ENV', 'development').lower()
IS_PRODUCTION = FLASK_ENV == 'production'
DEBUG_MODE = os.getenv('FLASK_DEBUG', 'false').lower() == 'true' and not IS_PRODUCTION
LAN_ACCESS = os.getenv('LAN_ACCESS', 'false').lower() == 'true'
PORT = int(os.getenv('PORT', '5000'))

_secret = os.getenv('FLASK_SECRET_KEY')
if not _secret or _secret == 'replace-with-a-long-random-secret':
    _secret = secrets.token_hex(32)
    if IS_PRODUCTION:
        raise RuntimeError('FLASK_SECRET_KEY must be set to a real secret in .env before running in production.')
    app.logger.warning(
        'FLASK_SECRET_KEY is not set in .env. Using a random secret for this process '
        'only -- everyone will be logged out on restart. Set FLASK_SECRET_KEY in .env to fix this.'
    )
app.secret_key = _secret

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=IS_PRODUCTION,
)

BACKEND = os.getenv('BACKEND_URL', 'http://127.0.0.1:8000').rstrip('/')
SAFE_METHODS = {'GET', 'HEAD', 'OPTIONS'}

# ---------------------------------------------------------------------------
# CSRF + security headers
# ---------------------------------------------------------------------------
def get_csrf_token():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_urlsafe(32)
    return session['csrf_token']


@app.context_processor
def inject_csrf():
    return dict(csrf_token=get_csrf_token())


@app.before_request
def enforce_csrf():
    if request.method in SAFE_METHODS or not request.path.startswith('/api/'):
        return None
    sent = request.headers.get('X-CSRF-Token', '')
    expected = session.get('csrf_token', '')
    if not expected or not sent or not secrets.compare_digest(sent, expected):
        return jsonify({'detail': 'Your session expired or is invalid. Please refresh the page and try again.'}), 403
    return None


@app.after_request
def security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer-when-downgrade'
    return response


@app.errorhandler(413)
def too_large(_e):
    return jsonify({'detail': 'File is too large (max 8 MB).'}), 413


# ---------------------------------------------------------------------------
# Backend proxy helpers
# ---------------------------------------------------------------------------
def _auth_headers():
    return {'Authorization': f"Bearer {session.get('token', '')}"}


def call(path, method='post', data=None, files=None, form=None, timeout=60):
    try:
        r = requests.request(method, f'{BACKEND}{path}', json=data, files=files, data=form, headers=_auth_headers(), timeout=timeout)
    except requests.RequestException as e:
        return jsonify({'detail': f'Backend connection failed: {e}'}), 503
    try:
        body = r.json()
    except ValueError:
        return jsonify({'detail': f'Backend returned an unexpected response (HTTP {r.status_code}).'}), 502
    if r.status_code == 401 and session.get('token'):
        session.pop('token', None); session.pop('user', None)  # backend session expired/revoked
    return jsonify(body), r.status_code


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@app.get('/')
def index():
    if session.get('token'):
        return redirect('/admin' if session.get('user', {}).get('role') == 'admin' else '/dashboard')
    return render_template('login.html')


@app.get('/register')
def register():
    if session.get('token'):
        return redirect('/dashboard')
    return render_template('register.html')


@app.get('/dashboard')
def dashboard():
    if not session.get('token'):
        return redirect('/')
    return render_template('dashboard.html', user=session['user'])


@app.get('/admin')
def admin():
    if not session.get('token') or session.get('user', {}).get('role') != 'admin':
        return redirect('/')
    return render_template('admin.html', user=session['user'])


# ---------------------------------------------------------------------------
# API (browser -> Flask -> FastAPI)
# ---------------------------------------------------------------------------
@app.post('/api/register')
def api_register():
    return call('/auth/register', data=request.json, timeout=20)


@app.post('/api/verify')
def api_verify():
    return call('/auth/verify', data=request.json, timeout=20)


@app.post('/api/resend-registration-otp')
def api_resend_registration_otp():
    return call('/auth/resend-registration-otp', data=request.json, timeout=20)


@app.post('/api/login')
def api_login():
    try:
        r = requests.post(BACKEND + '/auth/login', json=request.json, timeout=20)
        body = r.json()
        if r.ok:
            session['token'] = body['token']
            session['user'] = body['user']
            body = {'user': body['user']}  # the token never goes to the browser
        return jsonify(body), r.status_code
    except requests.RequestException as e:
        return jsonify({'detail': f'Backend connection failed: {e}'}), 503
    except ValueError:
        return jsonify({'detail': 'Backend returned an unexpected response.'}), 502


@app.post('/api/account-create-prepare')
def api_account_create_prepare():
    return call('/auth/account-create-prepare', data=request.json, timeout=20)


@app.post('/api/account-create-verify')
def api_account_create_verify():
    try:
        r = requests.post(BACKEND + '/auth/account-create-verify', json=request.json, timeout=20)
        body = r.json()
        if r.ok:
            session['token'] = body['token']
            session['user'] = body['user']
            body = {'user': body['user']}
        return jsonify(body), r.status_code
    except requests.RequestException as e:
        return jsonify({'detail': f'Backend connection failed: {e}'}), 503
    except ValueError:
        return jsonify({'detail': 'Backend returned an unexpected response.'}), 502


@app.post('/api/account-create-resend-otp')
def api_account_create_resend_otp():
    return call('/auth/account-create-resend-otp', data=request.json, timeout=20)


@app.post('/api/account-login-prepare')
def api_account_login_prepare():
    try:
        r = requests.post(BACKEND + '/auth/account-login-prepare', json=request.json, timeout=20)
        body = r.json()
        if r.ok and not body.get('needs_otp'):
            session['token'] = body['token']
            session['user'] = body['user']
            body = {'needs_otp': False, 'user': body['user']}
        return jsonify(body), r.status_code
    except requests.RequestException as e:
        return jsonify({'detail': f'Backend connection failed: {e}'}), 503
    except ValueError:
        return jsonify({'detail': 'Backend returned an unexpected response.'}), 502


@app.post('/api/account-login-verify')
def api_account_login_verify():
    try:
        r = requests.post(BACKEND + '/auth/account-login-verify', json=request.json, timeout=20)
        body = r.json()
        if r.ok:
            session['token'] = body['token']
            session['user'] = body['user']
            body = {'user': body['user']}
        return jsonify(body), r.status_code
    except requests.RequestException as e:
        return jsonify({'detail': f'Backend connection failed: {e}'}), 503
    except ValueError:
        return jsonify({'detail': 'Backend returned an unexpected response.'}), 502


@app.post('/api/account-login-resend-otp')
def api_account_login_resend_otp():
    return call('/auth/account-login-resend-otp', data=request.json, timeout=20)


@app.post('/api/logout')
def logout():
    if session.get('token'):
        try:
            requests.post(BACKEND + '/auth/logout', headers=_auth_headers(), timeout=10)
        except requests.RequestException:
            pass
    session.clear()
    return jsonify({'ok': True})


@app.post('/api/forgot')
def forgot():
    return call('/auth/forgot', data=request.json, timeout=20)


@app.post('/api/reset')
def reset():
    return call('/auth/reset', data=request.json, timeout=20)


@app.post('/api/predict')
def predict():
    return call('/predict', data=request.json, timeout=30)


@app.post('/api/ml/evaluate')
def api_ml_evaluate():
    return call('/ml/evaluate', data=request.json or {}, timeout=120)

@app.get('/api/ml/history')
def api_ml_history():
    return call('/ml/history', method='get', timeout=20)

@app.get('/api/ml/prediction-history')
def api_ml_prediction_history():
    return call('/ml/prediction-history', method='get', timeout=20)

@app.post('/api/admin/students/create')
def api_admin_create_student():
    return call('/admin/students/create', data=request.json, timeout=30)

@app.post('/api/admin/message')
def api_admin_message():
    return call('/admin/message', data=request.json, timeout=60)

@app.get('/api/notifications')
def api_notifications():
    return call('/notifications', method='get', timeout=20)

@app.post('/api/notifications/<int:nid>/read')
def api_notification_read(nid):
    return call(f'/notifications/{nid}/read', method='post', timeout=20)

@app.get('/api/profile')
def api_profile():
    return call('/profile', method='get', timeout=20)

@app.post('/api/profile')
def api_profile_save():
    return call('/profile', data=request.json, timeout=20)


@app.get('/api/agents')
def api_agents():
    return call('/agents', method='get', timeout=15)


@app.post('/api/agent/chat')
def api_agent_chat():
    return call('/agent/chat', data=request.json, timeout=240)


@app.post('/api/agent/research')
def api_agent_research():
    return call('/agent/research', data=request.json, timeout=300)


@app.post('/api/generate-image')
def image():
    return call('/generate-image', data=request.json, timeout=180)


@app.post('/api/library/upload')
def api_upload():
    f = request.files.get('file')
    if not f:
        return jsonify({'detail': 'No file received'}), 400
    return call('/library/upload', files={'file': (f.filename, f.stream, f.mimetype)},
                form={'source': request.form.get('source', 'upload')}, timeout=60)


@app.get('/api/library')
def api_library():
    return call('/library', method='get', timeout=20)


@app.delete('/api/library/<int:fid>')
def api_library_delete(fid):
    return call(f'/library/{fid}', method='delete', timeout=20)


@app.get('/api/files/<int:fid>')
def api_file(fid):
    if not session.get('token'):
        return jsonify({'detail': 'Login required'}), 401
    try:
        r = requests.get(f'{BACKEND}/library/{fid}/file', headers=_auth_headers(), timeout=30)
    except requests.RequestException as e:
        return jsonify({'detail': f'Backend connection failed: {e}'}), 503
    if r.status_code != 200:
        return jsonify({'detail': 'File not found'}), r.status_code
    resp = Response(r.content, mimetype=r.headers.get('Content-Type', 'application/octet-stream'))
    resp.headers['Content-Disposition'] = r.headers.get('Content-Disposition', 'attachment')
    resp.headers['Cache-Control'] = 'private, max-age=3600'
    return resp


@app.post('/api/resume/analyze')
def resume():
    f = request.files.get('file')
    if not f:
        return jsonify({'detail': 'PDF required'}), 400
    return call('/resume/analyze', files={'file': (f.filename, f.stream, f.mimetype)}, timeout=180)


@app.get('/api/admin/stats')
def admin_stats():
    return call('/admin/stats', method='get', timeout=20)


@app.post('/api/admin/user/<int:uid>/toggle')
def admin_toggle(uid):
    return call(f'/admin/user/{uid}/toggle', timeout=20)


# ---------------------------------------------------------------------------
# One-command launcher: `python app.py` starts Ollama (if installed), the
# FastAPI backend and this Flask app together.
# ---------------------------------------------------------------------------
def _port_open(host, port):
    try:
        with socket.create_connection((host, port), timeout=0.6):
            return True
    except OSError:
        return False


def _backend_healthy():
    try:
        return requests.get(BACKEND + '/health', timeout=1.5).ok
    except requests.RequestException:
        return False


def start_ollama_if_needed():
    if os.getenv('LLM_PROVIDER', 'auto').lower() == 'gemini' or _port_open('127.0.0.1', 11434) or not shutil.which('ollama'):
        return
    try:
        proc = subprocess.Popen(['ollama', 'serve'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        atexit.register(proc.terminate)
        print('Started Ollama in the background.')
    except OSError as e:
        print(f'Could not start Ollama automatically: {e}')


def start_backend_if_needed():
    host = urlparse(BACKEND).hostname
    if _backend_healthy():
        return
    if host not in ('127.0.0.1', 'localhost'):
        print(f'Backend at {BACKEND} is not reachable and is not local, so it was not started.')
        return
    env = os.environ.copy()
    proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1',
                             '--port', str(urlparse(BACKEND).port or 8000)], cwd=str(ROOT), env=env)
    atexit.register(proc.terminate)
    print('Starting backend (first run trains the ML model, this can take a minute)...')
    for _ in range(150):
        if _backend_healthy():
            print('Backend is ready.')
            return
        if proc.poll() is not None:
            print('Backend stopped unexpectedly. Run: python -m uvicorn backend.main:app  to see the error.')
            return
        time.sleep(1)
    print('Backend is still starting; the site will work once it finishes.')


def lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('8.8.8.8', 80))
            return s.getsockname()[0]
    except OSError:
        return None


def main():
    start_ollama_if_needed()
    start_backend_if_needed()
    host = '0.0.0.0' if LAN_ACCESS else '127.0.0.1'
    print(f'\n  PC:    http://127.0.0.1:{PORT}')
    if LAN_ACCESS:
        ip = lan_ip()
        if ip:
            print(f'  Phone: http://{ip}:{PORT}   (phone must be on the same Wi-Fi)')
    if not IS_PRODUCTION:
        Timer(1.2, lambda: __import__('webbrowser').open(f'http://127.0.0.1:{PORT}')).start()
    app.run(host=host, port=PORT, debug=DEBUG_MODE, use_reloader=False)


if __name__ == '__main__':
    main()
