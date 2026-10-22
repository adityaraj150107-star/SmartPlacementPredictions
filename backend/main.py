import os, smtplib, secrets, json, base64, io, logging
from pathlib import Path
from datetime import datetime, timedelta
from email.message import EmailMessage
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from dotenv import load_dotenv
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from .database import *
from .schemas import *
from .ml_model import load_model, train, METRICS, evaluate_algorithms, predict_with_algorithm, ALGORITHM_LABELS
from . import agents as ai
from . import files as filetools

load_dotenv(Path(__file__).resolve().parent / '.env')
init_db()

logging.basicConfig(level=logging.INFO)
log = logging.getLogger('smart_placement')

IS_PRODUCTION = os.getenv('FLASK_ENV', 'development').lower() == 'production'

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title='Smart Placement Predictions API', version='4.0')
app.state.limiter = limiter


def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    # Match the {"detail": "..."} shape the rest of the API and the frontend expect.
    return JSONResponse(status_code=429, content={'detail': f'Too many requests. Please slow down and try again shortly. ({exc.detail})'})


app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(CORSMiddleware, allow_origins=['http://127.0.0.1:5000', 'http://localhost:5000'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])

@app.middleware('http')
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer-when-downgrade'
    if IS_PRODUCTION:
        response.headers['Strict-Transport-Security'] = 'max-age=63072000; includeSubDomains'
    return response


MODEL = None


def current(auth):
    if not auth or not auth.startswith('Bearer '):
        raise HTTPException(401, 'Login required')
    db = get_session_user(auth[7:])
    if not db:
        raise HTTPException(401, 'Session expired or invalid, please log in again')
    if not db['active']:
        raise HTTPException(403, 'Account disabled')
    return db


def send_email(to, subject, body):
    host = os.getenv('SMTP_HOST', '').strip()
    port_raw = os.getenv('SMTP_PORT', '587').strip()
    username = os.getenv('SMTP_USERNAME', '').strip()
    password = os.getenv('SMTP_PASSWORD', '').strip()
    sender = (os.getenv('SMTP_FROM') or username).strip()

    if not host or not username or not password or not sender:
        raise RuntimeError(
            'SMTP is not configured. Set SMTP_HOST, SMTP_PORT, SMTP_USERNAME, '
            'SMTP_PASSWORD (Google App Password), and SMTP_FROM in the project .env file.'
        )
    placeholders = {'yourgmail@gmail.com', 'your_16_character_app_password', 'your_password', '...'}
    if username in placeholders or password in placeholders or sender in placeholders:
        raise RuntimeError('SMTP still contains placeholder values. Replace them with your real Gmail and Google App Password in .env.')
    try:
        port = int(port_raw)
    except ValueError:
        raise RuntimeError('SMTP_PORT must be 587 (STARTTLS) or 465 (SSL).')

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = to
    msg.set_content(body)

    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=30) as server:
                server.ehlo()
                server.login(username, password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(username, password)
                server.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        raise RuntimeError('Gmail SMTP authentication failed. Use a Google App Password, not your normal Gmail password.')
    except smtplib.SMTPConnectError as e:
        raise RuntimeError(f'Could not connect to SMTP server: {e}')
    except smtplib.SMTPException as e:
        raise RuntimeError(f'SMTP email failed: {e}')


def issue_otp(email, purpose):
    otp = f'{secrets.randbelow(1_000_000):06d}'
    exp = (datetime.utcnow() + timedelta(minutes=10)).isoformat()
    c = conn()
    c.execute('DELETE FROM otps WHERE email=? AND purpose=?', (email, purpose))
    c.execute('INSERT INTO otps(email,otp,purpose,expires_at,attempts) VALUES(?,?,?,?,0)', (email, otp, purpose, exp))
    c.commit(); c.close()
    send_email(email, f'Smart Placement Predictions - {purpose.title()} OTP', f'Your OTP is {otp}. It expires in 10 minutes.')


def verify_otp_or_raise(email, purpose, submitted_otp):
    """Checks an OTP with brute-force lockout. Raises HTTPException on any failure."""
    c = conn()
    r = c.execute('SELECT * FROM otps WHERE email=? AND purpose=? ORDER BY id DESC LIMIT 1', (email, purpose)).fetchone()
    c.close()
    if not r:
        raise HTTPException(400, 'Invalid or expired OTP. Please request a new one.')
    if r['attempts'] >= MAX_OTP_ATTEMPTS:
        invalidate_otp(r['id'])
        raise HTTPException(429, 'Too many incorrect attempts. Please request a new OTP.')
    if datetime.fromisoformat(r['expires_at']) < datetime.utcnow():
        invalidate_otp(r['id'])
        raise HTTPException(400, 'OTP expired. Please request a new one.')
    if r['otp'] != submitted_otp:
        attempts = register_otp_failure(r['id'])
        remaining = max(MAX_OTP_ATTEMPTS - attempts, 0)
        if remaining <= 0:
            invalidate_otp(r['id'])
            raise HTTPException(429, 'Too many incorrect attempts. Please request a new OTP.')
        raise HTTPException(400, f'Invalid OTP. {remaining} attempt(s) remaining.')
    invalidate_otp(r['id'])


@app.on_event('startup')
def startup():
    global MODEL
    try:
        MODEL = load_model()
    except Exception as e:
        log.warning('ML model startup warning: %s', e)
    cleanup_expired_sessions()


@app.get('/auth/session')
def auth_session(authorization: str = Header(None)):
    u = current(authorization)
    return {'user': {'id': u['id'], 'name': u['name'], 'email': u['email'], 'role': u['role']}}


@app.get('/health')
def health():
    return {'status': 'ok', 'service': 'Smart Placement Predictions API', 'ml_model_loaded': MODEL is not None, 'ollama_model': os.getenv('OLLAMA_MODEL', 'llama3.2')}


@app.post('/auth/register')
@limiter.limit('5/hour')
def register(request: Request, x: RegisterRequest):
    email = x.email.lower().strip()
    existing = get_user(email)
    if existing:
        # A half-finished registration should be recoverable from the website.
        # Verified accounts still get the normal duplicate-email response.
        if existing['role'] == 'student' and not existing['verified']:
            if len(x.password) < 8:
                raise HTTPException(400, 'Password must be at least 8 characters')
            c = conn()
            c.execute('UPDATE users SET name=?, password_hash=?, active=1 WHERE email=? AND role=? AND verified=0',
                      (x.name.strip(), hash_password(x.password), email, 'student'))
            c.commit(); c.close()
            try:
                issue_otp(email, 'registration')
            except Exception as e:
                raise HTTPException(503, f'Could not send verification email. {e}')
            return {'message': 'Your unfinished account was found. A fresh OTP was sent to your email.', 'resend': True}
        raise HTTPException(409, 'Email already registered. Please sign in or use Forgot password.')

    c = conn()
    c.execute('INSERT INTO users(name,email,password_hash,role,verified,active,created_at) VALUES(?,?,?,?,?,?,?)', (x.name.strip(), email, hash_password(x.password), 'student', 0, 1, datetime.utcnow().isoformat()))
    c.commit(); c.close()
    try:
        issue_otp(email, 'registration')
    except Exception as e:
        # Do not leave an unusable unverified account behind when mail delivery fails.
        c = conn()
        c.execute('DELETE FROM otps WHERE email=? AND purpose=?', (email, 'registration'))
        c.execute('DELETE FROM users WHERE email=? AND role=? AND verified=0', (email, 'student'))
        c.commit(); c.close()
        raise HTTPException(503, f'Could not send verification email. {e}')
    return {'message': 'Account created. OTP sent to your email.'}


@app.post('/auth/resend-registration-otp')
@limiter.limit('5/hour')
def resend_registration_otp(request: Request, x: dict):
    email = str(x.get('email', '')).strip().lower()
    if not email:
        raise HTTPException(400, 'Email address is required')
    u = get_user(email)
    if not u or u['role'] != 'student':
        # Do not reveal whether an email belongs to an account.
        raise HTTPException(400, 'If this is an unfinished student registration, a new OTP has been sent.')
    if u['verified']:
        raise HTTPException(400, 'This email is already verified. Please sign in.')
    try:
        issue_otp(email, 'registration')
    except Exception as e:
        raise HTTPException(503, f'Could not send verification email. {e}')
    return {'message': 'A new OTP has been sent to your email.'}


@app.post('/auth/verify')
@limiter.limit('10/minute')
def verify(request: Request, x: VerifyOTPRequest):
    verify_otp_or_raise(x.email.lower(), 'registration', x.otp)
    c = conn()
    c.execute('UPDATE users SET verified=1 WHERE email=?', (x.email.lower(),))
    c.commit(); c.close()
    return {'message': 'Email verified successfully'}


@app.post('/auth/login')
@limiter.limit('10/minute')
def login(request: Request, x: LoginRequest):
    u = get_user(x.email.lower())
    if not u or not check_password(x.password, u['password_hash']):
        raise HTTPException(401, 'Invalid email or password')
    if not u['verified']:
        raise HTTPException(403, 'Please verify your email first')
    if not u['active']:
        raise HTTPException(403, 'Account disabled by admin')
    t = create_session(u['id'])
    add_activity(u['id'], 'Login', u['role'])
    return {'token': t, 'user': {'id': u['id'], 'name': u['name'], 'email': u['email'], 'role': u['role']}}


@app.post('/auth/account-create-prepare')
@limiter.limit('5/hour')
def account_create_prepare(request: Request, x: RegisterRequest):
    email = x.email.lower().strip()
    existing = get_user(email)
    if existing:
        if existing['role'] == 'student' and not existing['verified']:
            c = conn()
            c.execute('UPDATE users SET name=?, password_hash=?, active=1 WHERE email=? AND role=? AND verified=0',
                      (x.name.strip(), hash_password(x.password), email, 'student'))
            c.commit(); c.close()
            try:
                issue_otp(email, 'account create')
            except Exception as e:
                raise HTTPException(503, f'Could not send verification email. {e}')
            return {'needs_otp': True, 'email': email, 'message': 'This unfinished account was found. A fresh OTP was sent to its email.'}
        raise HTTPException(409, 'Email already registered. Please use Sign in instead.')
    c = conn()
    c.execute('INSERT INTO users(name,email,password_hash,role,verified,active,created_at) VALUES(?,?,?,?,?,?,?)',
              (x.name.strip(), email, hash_password(x.password), 'student', 0, 1, datetime.utcnow().isoformat()))
    c.commit(); c.close()
    try:
        issue_otp(email, 'account create')
    except Exception as e:
        c = conn(); c.execute('DELETE FROM otps WHERE email=? AND purpose=?', (email, 'account create')); c.execute('DELETE FROM users WHERE email=? AND role=? AND verified=0', (email, 'student')); c.commit(); c.close()
        raise HTTPException(503, f'Could not send verification email. {e}')
    return {'needs_otp': True, 'email': email, 'message': 'Account created. A 6-digit OTP was sent to this email.'}


@app.post('/auth/account-create-verify')
@limiter.limit('10/minute')
def account_create_verify(request: Request, x: VerifyOTPRequest):
    email = x.email.lower().strip()
    u = get_user(email)
    if not u or u['role'] != 'student':
        raise HTTPException(401, 'Account not found')
    if not u['active']:
        raise HTTPException(403, 'Account disabled by admin')
    verify_otp_or_raise(email, 'account create', x.otp)
    c = conn(); c.execute('UPDATE users SET verified=1 WHERE email=?', (email,)); c.commit(); c.close()
    u = get_user(email)
    t = create_session(u['id'])
    add_activity(u['id'], 'Account Created From Switcher', u['role'])
    return {'token': t, 'user': {'id': u['id'], 'name': u['name'], 'email': u['email'], 'role': u['role']}}


@app.post('/auth/account-create-resend-otp')
@limiter.limit('5/hour')
def account_create_resend_otp(request: Request, x: dict):
    email = str(x.get('email', '')).strip().lower()
    u = get_user(email)
    if not u or u['role'] != 'student' or u['verified']:
        raise HTTPException(400, 'This account is already verified or was not found.')
    try:
        issue_otp(email, 'account create')
    except Exception as e:
        raise HTTPException(503, f'Could not send verification email. {e}')
    return {'message': 'A new OTP was sent to the account email.'}


@app.post('/auth/account-login-prepare')
@limiter.limit('10/minute')
def account_login_prepare(request: Request, x: LoginRequest):
    """Prepare the ChatGPT-style account switch flow.

    Verified accounts can switch immediately after password validation.
    An unverified account gets a fresh OTP to its own email and must complete
    the OTP step before the account is activated/switched.
    """
    email = x.email.lower().strip()
    u = get_user(email)
    if not u or not check_password(x.password, u['password_hash']):
        raise HTTPException(401, 'Invalid email or password')
    if not u['active']:
        raise HTTPException(403, 'Account disabled by admin')
    if u['verified']:
        t = create_session(u['id'])
        add_activity(u['id'], 'Account Switch Login', u['role'])
        return {'needs_otp': False, 'token': t, 'user': {'id': u['id'], 'name': u['name'], 'email': u['email'], 'role': u['role']}}
    try:
        issue_otp(email, 'account switch')
    except Exception as e:
        raise HTTPException(503, f'Could not send verification email. {e}')
    return {'needs_otp': True, 'message': 'This account is not verified yet. A 6-digit OTP was sent to its email.', 'email': email, 'user': {'id': u['id'], 'name': u['name'], 'email': u['email'], 'role': u['role']}}


@app.post('/auth/account-login-verify')
@limiter.limit('10/minute')
def account_login_verify(request: Request, x: VerifyOTPRequest):
    email = x.email.lower().strip()
    u = get_user(email)
    if not u:
        raise HTTPException(401, 'Account not found')
    if not u['active']:
        raise HTTPException(403, 'Account disabled by admin')
    verify_otp_or_raise(email, 'account switch', x.otp)
    c = conn()
    c.execute('UPDATE users SET verified=1 WHERE email=?', (email,))
    c.commit(); c.close()
    t = create_session(u['id'])
    add_activity(u['id'], 'Account Switch OTP Verified', u['role'])
    return {'token': t, 'user': {'id': u['id'], 'name': u['name'], 'email': u['email'], 'role': u['role']}}


@app.post('/auth/account-login-resend-otp')
@limiter.limit('5/hour')
def account_login_resend_otp(request: Request, x: dict):
    email = str(x.get('email', '')).strip().lower()
    if not email:
        raise HTTPException(400, 'Email address is required')
    u = get_user(email)
    if not u:
        raise HTTPException(400, 'Account not found')
    if u['verified']:
        raise HTTPException(400, 'This account is already verified. Enter the password to switch.')
    try:
        issue_otp(email, 'account switch')
    except Exception as e:
        raise HTTPException(503, f'Could not send verification email. {e}')
    return {'message': 'A new OTP has been sent to the account email.'}


@app.post('/auth/logout')
def logout(authorization: str = Header(None)):
    if authorization and authorization.startswith('Bearer '):
        delete_session(authorization[7:])
    return {'message': 'Logged out'}


@app.post('/auth/forgot')
@limiter.limit('5/hour')
def forgot(request: Request, x: dict):
    email = str(x.get('email', '')).lower()
    u = get_user(email)
    if not u:
        return {'message': 'If the account exists, a reset OTP has been sent.'}
    try:
        issue_otp(email, 'password reset')
    except Exception as e:
        raise HTTPException(500, f'Email could not be sent: {e}')
    return {'message': 'Password reset OTP sent.'}


@app.post('/auth/reset')
@limiter.limit('10/minute')
def reset(request: Request, x: dict):
    email = str(x.get('email', '')).lower()
    otp = str(x.get('otp', ''))
    password = str(x.get('password', ''))
    if len(password) < 8:
        raise HTTPException(400, 'Password must be at least 8 characters')
    verify_otp_or_raise(email, 'password reset', otp)
    u = get_user(email)
    c = conn()
    c.execute('UPDATE users SET password_hash=? WHERE email=?', (hash_password(password), email))
    c.commit(); c.close()
    if u:
        # Resetting the password invalidates every existing session for that
        # account, so a stolen token can't outlive a password change.
        delete_all_sessions_for_user(u['id'])
    return {'message': 'Password reset successfully'}


@app.get('/profile')
def profile_get(authorization: str = Header(None)):
    u=current(authorization)
    profile=get_student_profile(u['id']) or {'user_id':u['id'],'name':u['name'],'course':'','semester':'','college':'','cgpa':None,'tenth':None,'twelfth':None,'internship':0,'skills':''}
    return {'profile':profile}

@app.post('/profile')
def profile_save(x: StudentProfileRequest, authorization: str = Header(None)):
    u=current(authorization)
    profile=upsert_student_profile(u['id'], x.model_dump() if hasattr(x, 'model_dump') else x.dict())
    add_activity(u['id'],'Student Profile Updated',x.course)
    return {'message':'Student information saved successfully.','profile':profile}

@app.post('/predict')
def predict(x: PredictionRequest, authorization: str = Header(None)):
    global MODEL
    u = current(authorization)
    algorithm = getattr(x, 'algorithm', 'random_forest') or 'random_forest'
    if algorithm not in ALGORITHM_LABELS:
        raise HTTPException(400, 'Unsupported algorithm. Choose one of the four project algorithms.')
    row = {'ssc_p': x.tenth, 'hsc_p': x.twelfth, 'degree_p': x.cgpa * 10, 'workex': 'Yes' if x.internship else 'No', 'etest_p': x.aptitude, 'mba_p': x.mba_score, 'hsc_s': x.hsc_stream, 'degree_t': x.degree_type, 'specialisation': x.specialisation}
    try:
        probability, model_name = predict_with_algorithm(algorithm, row)
    except Exception as e:
        raise HTTPException(503, f'ML prediction unavailable: {e}')
    label = 'Likely to be Placed' if probability >= 50 else 'Needs Improvement'
    tips = []
    if x.tenth < 60:
        tips.append('Improve academic fundamentals and core subjects')
    if x.aptitude < 60:
        tips.append('Practice aptitude and logical reasoning tests')
    if not x.internship:
        tips.append('Try to complete at least one relevant internship')
    if x.cgpa < 7:
        tips.append('Focus on improving semester performance')
    if not tips:
        tips = ['Keep building strong projects', 'Practice interviews and communication', 'Maintain a consistent placement-preparation routine']
    save_prediction_history(u['id'], {'algorithm_key':algorithm,'algorithm':model_name,'probability':probability,'status':label,'course':getattr(x,'course',''),'cgpa':x.cgpa,'tenth':x.tenth,'twelfth':x.twelfth,'aptitude':x.aptitude,'internship':x.internship})
    add_activity(u['id'], 'Placement Prediction', f'{model_name}: {probability:.1f}%')
    return {'probability': probability, 'status': label, 'tips': tips, 'model': model_name, 'algorithm_key': algorithm, 'dataset': 'Campus Placement Dataset'}


@app.post('/ml/evaluate')
def evaluate_ml(authorization: str = Header(None)):
    u = current(authorization)
    try:
        results = evaluate_algorithms()
        save_model_accuracy_history(u['id'], results)
        add_activity(u['id'], 'ML Accuracy Evaluation', json.dumps({r['algorithm_key']: r['accuracy'] for r in results}))
        return {'results': results, 'evaluated_at': datetime.utcnow().isoformat(), 'note': 'All four algorithms were evaluated on the same reproducible 80/20 holdout split.'}
    except Exception as e:
        raise HTTPException(500, f'Algorithm evaluation failed: {e}')


@app.get('/ml/history')
def ml_history(authorization: str = Header(None)):
    u = current(authorization)
    return {'history': list_model_accuracy_history(u['id'])}


@app.get('/ml/prediction-history')
def ml_prediction_history(authorization: str = Header(None)):
    u = current(authorization)
    return {'history': list_prediction_history(u['id'])}


@app.post('/resume/analyze')
async def resume(file: UploadFile = File(...), authorization: str = Header(None)):
    u = current(authorization)
    data = await file.read()
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(400, 'Only PDF files are allowed')
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(400, 'PDF is too large (max 10 MB)')
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        text = '\n'.join((p.extract_text() or '') for p in reader.pages)
    except Exception as e:
        raise HTTPException(400, f'Could not read PDF: {e}')
    if not text.strip():
        raise HTTPException(400, 'No readable text found in PDF')
    try:
        feedback = ai.call_llm(ai.agent_system('resume'), [], 'Review this student resume for placement readiness. Return: 1) overall score /100, 2) strengths, 3) missing keywords/sections, 4) specific improvements, 5) interview preparation suggestions. Do not invent facts.\n\nRESUME:\n' + text[:18000])
    except Exception as e:
        feedback = f'AI resume review unavailable: {e}'
    add_activity(u['id'], 'Resume Analysis', file.filename)
    return {'filename': file.filename, 'characters': len(text), 'feedback': feedback, 'extracted_preview': text[:1500]}


UPLOAD_DIR = Path(__file__).resolve().parent / 'uploads'


def _store_file(user_id, kind_label, filename, data, kind, mime, ext, text=None):
    folder = UPLOAD_DIR / str(user_id)
    folder.mkdir(parents=True, exist_ok=True)
    stored = secrets.token_hex(16) + ext
    (folder / stored).write_bytes(data)
    item_id = add_library_item(user_id, kind_label, filetools.safe_filename(filename), mime, stored, len(data), text)
    return {'id': item_id, 'kind': kind_label, 'filename': filetools.safe_filename(filename), 'mime': mime,
            'size': len(data), 'is_image': kind == 'image', 'url': f'/api/files/{item_id}'}


@app.get('/agents')
def agents_list(authorization: str = Header(None)):
    current(authorization)
    return {'agents': ai.public_agents()}


@app.post('/library/upload')
@limiter.limit('40/minute')
async def library_upload(request: Request, file: UploadFile = File(...), source: str = Form('upload'), authorization: str = Header(None)):
    u = current(authorization)
    data = await file.read(filetools.MAX_UPLOAD_BYTES + 1)
    if len(data) > filetools.MAX_UPLOAD_BYTES:
        raise HTTPException(413, 'File is too large (max 8 MB)')
    if not data:
        raise HTTPException(400, 'Empty file')
    try:
        kind, mime, ext = filetools.sniff(data, file.filename)
    except ValueError as e:
        raise HTTPException(415, str(e))
    text = filetools.extract_text(kind, data) if kind != 'image' else None
    label = source if source in ('sketch', 'camera') else ('image' if kind == 'image' else 'document')
    add_activity(u['id'], 'File Upload', label)
    return _store_file(u['id'], label, file.filename or 'file', data, kind, mime, ext, text)


@app.get('/library')
def library_list(authorization: str = Header(None)):
    u = current(authorization)
    items = list_library(u['id'])
    for i in items:
        i['is_image'] = i['mime'].startswith('image/')
        i['url'] = f"/api/files/{i['id']}"
    return {'items': items}


@app.get('/library/{item_id}/file')
def library_file(item_id: int, authorization: str = Header(None)):
    u = current(authorization)
    item = get_library_item(item_id, u['id'])
    path = UPLOAD_DIR / str(u['id']) / item['stored_name'] if item else None
    if not item or not path.exists():
        raise HTTPException(404, 'File not found')
    disp = 'inline' if item['mime'].startswith('image/') else 'attachment'
    return Response(path.read_bytes(), media_type=item['mime'],
                    headers={'Content-Disposition': f'{disp}; filename="{item["filename"]}"', 'X-Content-Type-Options': 'nosniff'})


@app.delete('/library/{item_id}')
def library_delete(item_id: int, authorization: str = Header(None)):
    u = current(authorization)
    item = delete_library_item(item_id, u['id'])
    if not item:
        raise HTTPException(404, 'File not found')
    try:
        (UPLOAD_DIR / str(u['id']) / item['stored_name']).unlink(missing_ok=True)
    except OSError:
        pass
    return {'deleted': item_id}


def _clean_history(history):
    out = []
    for h in history[-10:]:
        role = 'assistant' if h.get('role') == 'assistant' else 'user'
        content = str(h.get('content', ''))[:4000]
        if content.strip():
            out.append({'role': role, 'content': content})
    return out


def _build_payload(user_id, message, attachment_ids):
    """Combine the typed message with attached files: documents become text the model
    reads, images are passed to a vision-capable model."""
    text, images, notes, budget = message.strip(), [], [], 24000
    for aid in attachment_ids:
        item = get_library_item(aid, user_id)
        if not item:
            raise HTTPException(404, f'Attachment {aid} not found')
        if item['mime'].startswith('image/'):
            path = UPLOAD_DIR / str(user_id) / item['stored_name']
            if path.exists():
                images.append((item['mime'], path.read_bytes()))
            notes.append(f'[Attached image: {item["filename"]}]')
        else:
            excerpt = (item.get('text_excerpt') or '')[:min(12000, budget)]
            budget -= len(excerpt)
            notes.append(f'[Attached file: {item["filename"]}]\n{excerpt or "(no readable text found)"}')
    if notes:
        text = (text or 'Please look at the attached file(s) and help me.') + '\n\n---\n' + '\n\n'.join(notes)
    if not text:
        raise HTTPException(400, 'Type a message or attach a file')
    return text, images


def _agent_endpoint(u, x, mode_allowed):
    if x.mode not in mode_allowed:
        raise HTTPException(400, f'Unsupported mode: {x.mode}')
    text, images = _build_payload(u['id'], x.message, x.attachment_ids)
    return text, images, ai.agent_system(x.agent), _clean_history(x.history)


@app.post('/agent/chat')
@limiter.limit('30/minute')
def agent_chat(request: Request, x: AgentChatRequest, authorization: str = Header(None)):
    u = current(authorization)
    text, images, system, history = _agent_endpoint(u, x, {'chat', 'search', 'visualize'})
    try:
        if x.mode == 'search':
            add_activity(u['id'], 'Web Search', x.message[:200])
            return {'mode': 'search', **ai.search_answer(system, history, text, images)}
        if x.mode == 'visualize':
            add_activity(u['id'], 'Visualize', x.message[:200])
            return {'mode': 'visualize', 'html': ai.visualize(text, images)}
        add_activity(u['id'], 'AI Assistant', x.agent)
        return {'mode': 'chat', 'answer': ai.call_llm(system, history, text, images)}
    except ai.LLMUnavailable as e:
        raise HTTPException(503, str(e))
    except ValueError as e:
        raise HTTPException(502, str(e))
    except Exception as e:
        raise HTTPException(502, f'{x.mode.title()} failed: {e}')


@app.post('/agent/research')
@limiter.limit('4/minute')
def agent_research(request: Request, x: AgentChatRequest, authorization: str = Header(None)):
    u = current(authorization)
    text, images, system, _ = _agent_endpoint(u, x, {'research'})
    try:
        add_activity(u['id'], 'Deep Research', x.message[:200])
        return {'mode': 'research', **ai.deep_research(system, text, images)}
    except ai.LLMUnavailable as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        raise HTTPException(502, f'Research failed: {e}')


@app.post('/generate-image')
@limiter.limit('10/minute')
def image(request: Request, x: ImageRequest, authorization: str = Header(None)):
    u = current(authorization)
    key = ai._gemini_key()
    model_name = os.getenv('GEMINI_IMAGE_MODEL', 'gemini-3.1-flash-image').strip()
    if not key:
        raise HTTPException(503, 'GEMINI_API_KEY is not configured in .env')
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=key)
        response = client.models.generate_content(model=model_name, contents=x.prompt, config=types.GenerateContentConfig(response_modalities=['TEXT', 'IMAGE']))
        for part in response.candidates[0].content.parts:
            if getattr(part, 'inline_data', None):
                raw = part.inline_data.data
                if isinstance(raw, str):
                    raw = base64.b64decode(raw)
                kind, mime, ext = filetools.sniff(raw, 'generated.png')
                item = _store_file(u['id'], 'generated', 'ai-image.png' if ext == '.png' else f'ai-image{ext}', raw, kind, mime, ext)
                add_activity(u['id'], 'Image Generation', x.prompt)
                return {'image_url': item['url'], 'id': item['id'], 'prompt': x.prompt, 'model': model_name}
        raise RuntimeError('Image model returned no image data')
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f'Image generation failed: {e}')


@app.get('/admin/stats')
def stats(authorization: str = Header(None)):
    u = current(authorization)
    if u['role'] != 'admin':
        raise HTTPException(403, 'Admin access required')
    c = conn()
    users = c.execute('SELECT COUNT(*) n FROM users WHERE role="student"').fetchone()['n']
    verified = c.execute('SELECT COUNT(*) n FROM users WHERE role="student" AND verified=1').fetchone()['n']
    active = c.execute('SELECT COUNT(*) n FROM users WHERE role="student" AND active=1').fetchone()['n']
    predictions = c.execute('SELECT COUNT(*) n FROM activity WHERE action="Placement Prediction"').fetchone()['n']
    resumes = c.execute('SELECT COUNT(*) n FROM activity WHERE action="Resume Analysis"').fetchone()['n']
    ai = c.execute('SELECT COUNT(*) n FROM activity WHERE action="AI Assistant"').fetchone()['n']
    searches = c.execute('SELECT COUNT(*) n FROM activity WHERE action="Web Search"').fetchone()['n']
    images = c.execute('SELECT COUNT(*) n FROM activity WHERE action="Image Generation"').fetchone()['n']
    research = c.execute('SELECT COUNT(*) n FROM activity WHERE action="Deep Research"').fetchone()['n']
    visuals = c.execute('SELECT COUNT(*) n FROM activity WHERE action="Visualize"').fetchone()['n']
    rows = c.execute('SELECT id,name,email,verified,active,created_at FROM users WHERE role="student" ORDER BY id DESC').fetchall()
    c.close()
    metrics = {}
    try:
        metrics = json.loads(METRICS.read_text())
    except Exception:
        pass
    return {'stats': {'students': users, 'verified': verified, 'active': active, 'predictions': predictions, 'resumes': resumes, 'ai_usage': ai, 'web_searches': searches, 'images': images, 'deep_research': research, 'visualizations': visuals}, 'model_metrics': metrics, 'users': [dict(r) for r in rows]}



@app.post('/admin/message')
def admin_message(payload: dict, authorization: str = Header(None)):
    admin = current(authorization)
    if admin['role'] != 'admin':
        raise HTTPException(403, 'Admin access required')
    title = str(payload.get('title','')).strip()
    message = str(payload.get('message','')).strip()
    recipient = str(payload.get('recipient','all')).strip()
    if not title or not message:
        raise HTTPException(400, 'Title and message are required')
    c = conn()
    if recipient == 'all':
        rows = c.execute('SELECT id,email,name FROM users WHERE role="student" AND active=1').fetchall()
    else:
        rows = c.execute('SELECT id,email,name FROM users WHERE id=? AND role="student" AND active=1', (int(recipient),)).fetchall()
    c.close()
    if not rows:
        raise HTTPException(404, 'No active student recipient found')
    sent = 0
    failed = []
    for row in rows:
        add_notification(row['id'], title, message)
        try:
            send_email(row['email'], f'Smart Placement Predictions - {title}', f'Hello {row["name"]},\n\n{message}\n\nRegards,\nSmart Placement Predictions Admin')
            sent += 1
        except Exception as e:
            failed.append({'email': row['email'], 'error': str(e)})
    add_activity(admin['id'], 'Admin Message', json.dumps({'title':title,'recipient':recipient,'recipients':len(rows),'emails_sent':sent}))
    return {'message': f'Message saved for {len(rows)} student(s). Email sent to {sent}.', 'recipients': len(rows), 'emails_sent': sent, 'email_failures': failed}


@app.get('/notifications')
def notifications(authorization: str = Header(None)):
    u = current(authorization)
    return {'notifications': list_notifications(u['id'])}


@app.post('/notifications/{nid}/read')
def notification_read(nid: int, authorization: str = Header(None)):
    u = current(authorization)
    if not mark_notification_read(nid, u['id']):
        raise HTTPException(404, 'Notification not found')
    return {'ok': True}


@app.post('/admin/students/create')
def admin_create_student(payload: dict, authorization: str = Header(None)):
    admin = current(authorization)
    if admin['role'] != 'admin':
        raise HTTPException(403, 'Admin access required')
    name = str(payload.get('name','')).strip()
    email = str(payload.get('email','')).strip().lower()
    password = str(payload.get('password',''))
    course = str(payload.get('course','Other')).strip()
    if not name or not email or not password:
        raise HTTPException(400, 'Name, email and temporary password are required')
    if len(password) < 8:
        raise HTTPException(400, 'Temporary password must be at least 8 characters')
    if get_user(email):
        raise HTTPException(409, 'Email already registered')
    c = conn()
    cur = c.execute('INSERT INTO users(name,email,password_hash,role,verified,active,created_at) VALUES(?,?,?,?,?,?,?)',
                    (name,email,hash_password(password),'student',1,1,datetime.utcnow().isoformat()))
    uid = cur.lastrowid
    c.commit(); c.close()
    upsert_student_profile(uid, {'name':name,'course':course,'semester':'','college':'','cgpa':None,'tenth':None,'twelfth':None,'internship':0,'skills':''})
    title='Student account created by Admin'
    message=(f'Your Smart Placement Predictions student account has been created by the administrator.\n\n'
             f'Course: {course}\nEmail: {email}\n'
             'You can now log in using the temporary password provided by the administrator. '
             'Please change your password after first login.')
    add_notification(uid,title,message)
    email_error=None
    try:
        send_email(email, f'Smart Placement Predictions - {title}', f'Hello {name},\n\n{message}\n\nRegards,\nSmart Placement Predictions Admin')
    except Exception as e:
        email_error=str(e)
    add_activity(admin['id'],'Admin Added Student',json.dumps({'student_id':uid,'email':email,'email_sent':not bool(email_error)}))
    return {'message':'Student account created.', 'email_sent':not bool(email_error), 'email_error':email_error}


@app.post('/admin/retrain')
def retrain(authorization: str = Header(None)):
    u = current(authorization)
    if u['role'] != 'admin':
        raise HTTPException(403, 'Admin access required')
    global MODEL
    try:
        metrics = train()
        MODEL = load_model()
        add_activity(u['id'], 'Model Retrained', json.dumps(metrics))
        return {'message': 'Model retrained successfully', 'metrics': metrics}
    except Exception as e:
        raise HTTPException(500, f'Model training failed: {e}')


@app.post('/admin/user/{uid}/toggle')
def toggle(uid: int, authorization: str = Header(None)):
    u = current(authorization)
    if u['role'] != 'admin':
        raise HTTPException(403, 'Admin access required')
    c = conn()
    r = c.execute('SELECT active FROM users WHERE id=? AND role="student"', (uid,)).fetchone()
    if not r:
        c.close()
        raise HTTPException(404, 'Student not found')
    val = 0 if r['active'] else 1
    c.execute('UPDATE users SET active=? WHERE id=?', (val, uid))
    c.commit(); c.close()
    if val == 0:
        # Disabling a student should kick them out of any active sessions immediately.
        delete_all_sessions_for_user(uid)
    return {'active': val}
