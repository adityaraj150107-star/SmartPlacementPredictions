import os, sqlite3, secrets, hashlib, warnings
import bcrypt
from pathlib import Path
from datetime import datetime, timedelta

DB = Path(__file__).resolve().parent / "placement.db"

# How long a login session stays valid without re-authenticating.
SESSION_TTL_DAYS = float(os.getenv('SESSION_TTL_DAYS', '7'))
# How many wrong OTP guesses are allowed before that OTP is invalidated.
MAX_OTP_ATTEMPTS = int(os.getenv('MAX_OTP_ATTEMPTS', '5'))

INSECURE_ADMIN_PASSWORDS = {'admin@12345', 'admin123', 'password', 'changethisadminpassword123!', ''}


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    return c


def init_db():
    c = conn(); cur = c.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,role TEXT NOT NULL DEFAULT 'student',verified INTEGER DEFAULT 0,
        active INTEGER DEFAULT 1,created_at TEXT NOT NULL)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS otps(
        id INTEGER PRIMARY KEY AUTOINCREMENT,email TEXT NOT NULL,otp TEXT NOT NULL,
        purpose TEXT NOT NULL,expires_at TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS activity(
        id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,action TEXT,details TEXT,created_at TEXT NOT NULL)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS notifications(
        id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,title TEXT NOT NULL,message TEXT NOT NULL,
        is_read INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS student_profiles(
        user_id INTEGER PRIMARY KEY,name TEXT NOT NULL,course TEXT DEFAULT '',semester TEXT DEFAULT '',college TEXT DEFAULT '',
        cgpa REAL,tenth REAL,twelfth REAL,internship INTEGER DEFAULT 0,skills TEXT DEFAULT '',updated_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS model_accuracy_history(
        id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,
        algorithm_key TEXT NOT NULL,algorithm TEXT NOT NULL,accuracy REAL NOT NULL,
        precision REAL NOT NULL,recall REAL NOT NULL,f1 REAL NOT NULL,
        dataset_rows INTEGER NOT NULL,test_rows INTEGER NOT NULL,evaluated_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS prediction_history(
        id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,
        algorithm_key TEXT NOT NULL,algorithm TEXT NOT NULL,probability REAL NOT NULL,
        status TEXT NOT NULL,course TEXT DEFAULT '',cgpa REAL,tenth REAL,twelfth REAL,
        aptitude REAL,internship INTEGER,created_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE)''')
    # Sessions are persisted (survive backend restarts) and carry an expiry so a
    # leaked/old token cannot be used forever. Only the SHA-256 hash of the raw
    # token is stored, mirroring how the password hash is stored.
    cur.execute('''CREATE TABLE IF NOT EXISTS sessions(
        token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL,created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,last_seen TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id))''')
    c.commit()
    c.close()
    init_library()
    c = conn(); cur = c.cursor()

    # Defensive migration: older databases created before this column existed.
    existing_cols = {row['name'] for row in cur.execute("PRAGMA table_info(otps)").fetchall()}
    if 'attempts' not in existing_cols:
        cur.execute('ALTER TABLE otps ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0')
        c.commit()

    admin_email = os.getenv('ADMIN_EMAIL', 'admin@smartplacement.local')
    admin_pw = os.getenv('ADMIN_PASSWORD', 'Admin@12345')
    if admin_pw.strip().lower() in INSECURE_ADMIN_PASSWORDS:
        warnings.warn(
            'ADMIN_PASSWORD is missing or is a well-known default. Set a strong, '
            'unique ADMIN_PASSWORD in your .env file before exposing this app to anyone.',
            stacklevel=2,
        )
    if not cur.execute('SELECT 1 FROM users WHERE email=?', (admin_email,)).fetchone():
        cur.execute('INSERT INTO users(name,email,password_hash,role,verified,active,created_at) VALUES(?,?,?,?,?,?,?)',
                    ('System Admin', admin_email, hash_password(admin_pw), 'admin', 1, 1, datetime.utcnow().isoformat()))
        c.commit()
    c.close()


def hash_password(p):
    return bcrypt.hashpw(p.encode('utf-8'), bcrypt.gensalt(rounds=12)).decode('utf-8')


def check_password(p, h):
    try:
        return bcrypt.checkpw(p.encode('utf-8'), h.encode('utf-8'))
    except Exception:
        return False


def get_user(email):
    c = conn(); r = c.execute('SELECT * FROM users WHERE email=?', (email.lower(),)).fetchone(); c.close()
    return dict(r) if r else None


def get_user_by_id(uid):
    c = conn(); r = c.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone(); c.close()
    return dict(r) if r else None


def add_activity(uid, action, details=''):
    c = conn(); c.execute('INSERT INTO activity(user_id,action,details,created_at) VALUES(?,?,?,?)',
                           (uid, action, details, datetime.utcnow().isoformat())); c.commit(); c.close()


# ---------------------------------------------------------------------------
# Sessions (persistent, expiring, revocable)
# ---------------------------------------------------------------------------

def _hash_token(raw_token):
    return hashlib.sha256(raw_token.encode('utf-8')).hexdigest()


def create_session(user_id, ttl_days=None):
    """Create a new session and return the raw token to hand to the client.
    Only the hash of the token is ever stored server-side."""
    raw = secrets.token_urlsafe(32)
    now = datetime.utcnow()
    expires = now + timedelta(days=ttl_days if ttl_days is not None else SESSION_TTL_DAYS)
    c = conn()
    c.execute('INSERT INTO sessions(token_hash,user_id,created_at,expires_at,last_seen) VALUES(?,?,?,?,?)',
              (_hash_token(raw), user_id, now.isoformat(), expires.isoformat(), now.isoformat()))
    c.commit(); c.close()
    return raw


def get_session_user(raw_token):
    """Return the user dict for a valid, non-expired session token, else None.
    Also opportunistically prunes expired sessions and touches last_seen."""
    if not raw_token:
        return None
    token_hash = _hash_token(raw_token)
    c = conn()
    row = c.execute('SELECT * FROM sessions WHERE token_hash=?', (token_hash,)).fetchone()
    if not row:
        c.close(); return None
    if datetime.fromisoformat(row['expires_at']) < datetime.utcnow():
        c.execute('DELETE FROM sessions WHERE token_hash=?', (token_hash,)); c.commit(); c.close()
        return None
    c.execute('UPDATE sessions SET last_seen=? WHERE token_hash=?', (datetime.utcnow().isoformat(), token_hash))
    c.commit()
    user = c.execute('SELECT * FROM users WHERE id=?', (row['user_id'],)).fetchone()
    c.close()
    return dict(user) if user else None


def delete_session(raw_token):
    if not raw_token:
        return
    c = conn(); c.execute('DELETE FROM sessions WHERE token_hash=?', (_hash_token(raw_token),)); c.commit(); c.close()


def delete_all_sessions_for_user(user_id):
    """Force-logout a user everywhere. Used on password reset and admin disable."""
    c = conn(); c.execute('DELETE FROM sessions WHERE user_id=?', (user_id,)); c.commit(); c.close()


def cleanup_expired_sessions():
    c = conn(); c.execute('DELETE FROM sessions WHERE expires_at<?', (datetime.utcnow().isoformat(),)); c.commit(); c.close()


# ---------------------------------------------------------------------------
# OTP helpers with brute-force lockout
# ---------------------------------------------------------------------------

def register_otp_failure(otp_row_id):
    """Increment the attempt counter for a given OTP row. Returns the new count."""
    c = conn()
    c.execute('UPDATE otps SET attempts=attempts+1 WHERE id=?', (otp_row_id,))
    c.commit()
    row = c.execute('SELECT attempts FROM otps WHERE id=?', (otp_row_id,)).fetchone()
    c.close()
    return row['attempts'] if row else MAX_OTP_ATTEMPTS


def invalidate_otp(otp_row_id):
    c = conn(); c.execute('DELETE FROM otps WHERE id=?', (otp_row_id,)); c.commit(); c.close()


# ---------------------------------------------------------------------------
# Per-user file library (uploads, sketches, generated images)
# ---------------------------------------------------------------------------

def init_library():
    c = conn()
    c.execute('''CREATE TABLE IF NOT EXISTS library(
        id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,kind TEXT NOT NULL,
        filename TEXT NOT NULL,mime TEXT NOT NULL,stored_name TEXT NOT NULL,size INTEGER NOT NULL,
        text_excerpt TEXT,created_at TEXT NOT NULL,FOREIGN KEY(user_id) REFERENCES users(id))''')
    c.commit(); c.close()


def add_library_item(user_id, kind, filename, mime, stored_name, size, text_excerpt=None):
    c = conn()
    cur = c.execute('INSERT INTO library(user_id,kind,filename,mime,stored_name,size,text_excerpt,created_at) VALUES(?,?,?,?,?,?,?,?)',
                    (user_id, kind, filename, mime, stored_name, size, text_excerpt, datetime.utcnow().isoformat()))
    c.commit(); item_id = cur.lastrowid; c.close()
    return item_id


def list_library(user_id, limit=60):
    c = conn()
    rows = c.execute('SELECT id,kind,filename,mime,size,created_at FROM library WHERE user_id=? ORDER BY id DESC LIMIT ?', (user_id, limit)).fetchall()
    c.close()
    return [dict(r) for r in rows]


def get_library_item(item_id, user_id):
    """Ownership is enforced here: a user can never fetch someone else's file."""
    c = conn()
    r = c.execute('SELECT * FROM library WHERE id=? AND user_id=?', (item_id, user_id)).fetchone()
    c.close()
    return dict(r) if r else None


def delete_library_item(item_id, user_id):
    c = conn()
    r = c.execute('SELECT stored_name FROM library WHERE id=? AND user_id=?', (item_id, user_id)).fetchone()
    if r:
        c.execute('DELETE FROM library WHERE id=?', (item_id,)); c.commit()
    c.close()
    return dict(r) if r else None


def get_student_profile(user_id):
    c=conn(); r=c.execute('SELECT * FROM student_profiles WHERE user_id=?',(user_id,)).fetchone(); c.close(); return dict(r) if r else None

def upsert_student_profile(user_id, data):
    now=datetime.utcnow().isoformat(); c=conn()
    c.execute('''INSERT INTO student_profiles(user_id,name,course,semester,college,cgpa,tenth,twelfth,internship,skills,updated_at)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?)
                 ON CONFLICT(user_id) DO UPDATE SET name=excluded.name,course=excluded.course,semester=excluded.semester,
                 college=excluded.college,cgpa=excluded.cgpa,tenth=excluded.tenth,twelfth=excluded.twelfth,
                 internship=excluded.internship,skills=excluded.skills,updated_at=excluded.updated_at''',
              (user_id,data.get('name',''),data.get('course',''),data.get('semester',''),data.get('college',''),
               data.get('cgpa'),data.get('tenth'),data.get('twelfth'),data.get('internship',0),data.get('skills',''),now))
    c.commit(); r=c.execute('SELECT * FROM student_profiles WHERE user_id=?',(user_id,)).fetchone(); c.close(); return dict(r)


def add_notification(user_id, title, message):
    c=conn(); cur=c.execute('INSERT INTO notifications(user_id,title,message,is_read,created_at) VALUES(?,?,?,?,?)',
                            (user_id,title,message,0,datetime.utcnow().isoformat())); c.commit(); nid=cur.lastrowid; c.close(); return nid


def list_notifications(user_id, limit=30):
    c=conn(); rows=c.execute('SELECT id,title,message,is_read,created_at FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT ?',
                             (user_id,limit)).fetchall(); c.close(); return [dict(r) for r in rows]


def mark_notification_read(notification_id, user_id):
    c=conn(); cur=c.execute('UPDATE notifications SET is_read=1 WHERE id=? AND user_id=?',(notification_id,user_id)); c.commit(); changed=cur.rowcount; c.close(); return changed


# ---------------------------------------------------------------------------
# ML evaluation history
# ---------------------------------------------------------------------------
def save_model_accuracy_history(user_id, results):
    now = datetime.utcnow().isoformat()
    c = conn()
    for r in results:
        c.execute('''INSERT INTO model_accuracy_history
            (user_id,algorithm_key,algorithm,accuracy,precision,recall,f1,dataset_rows,test_rows,evaluated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?)''',
            (user_id,r['algorithm_key'],r['algorithm'],r['accuracy'],r['precision'],r['recall'],r['f1'],r['dataset_rows'],r['test_rows'],now))
    c.commit(); c.close()

def list_model_accuracy_history(user_id, limit=40):
    c=conn()
    rows=c.execute('''SELECT id,algorithm_key,algorithm,accuracy,precision,recall,f1,dataset_rows,test_rows,evaluated_at
                      FROM model_accuracy_history WHERE user_id=? ORDER BY id DESC LIMIT ?''',(user_id,limit)).fetchall()
    c.close()
    return [dict(r) for r in rows]


def save_prediction_history(user_id, data):
    c=conn()
    cur=c.execute('''INSERT INTO prediction_history
        (user_id,algorithm_key,algorithm,probability,status,course,cgpa,tenth,twelfth,aptitude,internship,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
        (user_id,data['algorithm_key'],data['algorithm'],data['probability'],data['status'],data.get('course',''),data.get('cgpa'),data.get('tenth'),data.get('twelfth'),data.get('aptitude'),data.get('internship',0),datetime.utcnow().isoformat()))
    c.commit(); pid=cur.lastrowid; c.close(); return pid

def list_prediction_history(user_id, limit=30):
    c=conn(); rows=c.execute('''SELECT id,algorithm_key,algorithm,probability,status,course,cgpa,tenth,twelfth,aptitude,internship,created_at
                               FROM prediction_history WHERE user_id=? ORDER BY id DESC LIMIT ?''',(user_id,limit)).fetchall(); c.close(); return [dict(r) for r in rows]
