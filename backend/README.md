# Smart Placement Predictions — AI BCA Project

A Flask + FastAPI project for student placement preparation with:

- Simple email + password login — one login screen for both Students and Admin, role opens automatically
- ChatGPT-style multi-account switcher in the dashboard with “Add another account”; each account keeps its own data/history
- Email OTP registration and password reset, with brute-force lockout after repeated wrong guesses
- Persistent, expiring, revocable login sessions (SQLite-backed, survive backend restarts)
- SQLite user/activity persistence
- Four ML algorithms — Random Forest, Logistic Regression, Decision Tree and SVM — with manual accuracy/precision/recall/F1 evaluation and SQLite-saved history
- Student placement prediction history saved per account, plus an automatic offline fallback dataset if the real dataset can't be downloaded
- PDF resume extraction + LangChain/Ollama review
- Conversational AI assistant with Ollama
- Live web search through DDGS
- Gemini image generation
- Professional responsive HTML/CSS/JavaScript UI with animations
- Admin user management and usage statistics
- Rate limiting on every auth endpoint, CSRF protection, hardened cookies, and security headers
- An automated backend test suite (pytest)

## AI Agent Hub (dashboard)

The dashboard opens with a ChatGPT-style workspace that works on phone and PC:

- **8 AI agents** — Smart AI, Placement Coach, Resume Expert, Interview Trainer, Aptitude Tutor, Coding Mentor, Career Guide, Project Helper. Each keeps its own conversation.
- **"+" menu** — Add photos & files (images, PDF, DOCX, code/text), Take photo (phones), Add from library, Create image, Sketch, Web search, Deep research, Visualize.
- **Sketch** — draw with finger or mouse, attach the drawing, and ask the AI about it (needs `GEMINI_API_KEY`, since local text models cannot see images).
- **Web search** — live results summarised with numbered source links.
- **Deep research** — plans several searches, reads the pages, and writes a cited report.
- **Visualize** — generates interactive charts/diagrams/tools, shown in a locked-down sandbox (no network, no access to your account).
- **Library** — everything you upload or create is saved privately per user and can be re-attached later.

The AI model is **Ollama** (free, local) by default, with **Gemini** as an automatic fallback or for images. See `backend/.env.example`.

## What's new / hardened in this version

This build closes the gaps a plain student-project skeleton usually has:

| Area | Before | Now |
|---|---|---|
| Login sessions | In-memory dict; wiped on every backend restart; tokens never expired | Persisted in SQLite, hashed at rest, expire after `SESSION_TTL_DAYS`, revocable (logout / password reset / admin-disable all invalidate them) |
| Brute force | Unlimited OTP guesses; unlimited login attempts | OTP locks out after `MAX_OTP_ATTEMPTS` wrong guesses; every auth endpoint is rate-limited per IP |
| Secrets | Silent insecure defaults (`change-me`, `Admin@12345`) | Warns loudly on startup if you haven't set your own, and refuses to start in `FLASK_ENV=production` without a real `FLASK_SECRET_KEY` |
| Debug mode | Flask always ran with `debug=True` | Off by default; only enabled via `FLASK_DEBUG=true`, and force-disabled in production |
| CSRF | None | Double-submit CSRF token required on every state-changing `/api/*` request |
| Cookies | Default Flask cookie | `HttpOnly`, `SameSite=Lax`, `Secure` in production |
| Client-side auth token | Duplicated in `localStorage` (dead code, unnecessary XSS surface) | Removed — the browser never sees the token; auth lives in the `HttpOnly` session cookie only |
| Dataset download | Hard failure if GitHub/network was unreachable | Retries automatically, then falls back to a small synthetic dataset so the app still runs end-to-end offline |
| ML comparison | Single Random Forest | Four algorithms can be evaluated manually on the same reproducible 80/20 split; every run is saved per student account |
| Prediction history | Activity log only | Dedicated prediction history stores algorithm, probability, status, inputs and timestamp |
| Accounts | One active browser login | Dashboard account switcher/“Add another account” lets users sign into many registered emails from the same UI |
| Security headers | None | `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, HSTS in production |
| Tests | None | `pytest` suite covering auth, OTP lockout, session revocation, and the offline ML fallback |

None of this changes how you use the app day-to-day — same URLs, same UI, same setup steps below.

## 1. Project structure

The root folder only has three things: `app.py` and the `backend/` and `frontend/` folders.
Everything else (this README, `.env`, `requirements.txt`, launchers, tests) lives inside `backend/`.

```text
SmartPlacementPredictions/
├── app.py                       # run this: starts everything (project root)
├── backend/
│   ├── README.md                # you are here
│   ├── requirements.txt
│   ├── .env.example             # copy to .env and fill in
│   ├── pytest.ini
│   ├── start_all.bat            # Windows: same as `python app.py`
│   ├── start_backend.bat        # optional: run only the FastAPI backend
│   ├── main.py                  # FastAPI backend (auth, rate limiting, predictions, admin)
│   ├── database.py              # SQLite users/sessions/OTP/activity
│   ├── schemas.py
│   ├── ml_model.py              # training + offline fallback dataset
│   ├── agents.py                # 8 agents, LLM (Ollama/Gemini), search, research, visualize
│   ├── files.py                 # upload sniffing + text extraction
│   ├── data/                    # dataset (downloaded automatically)
│   ├── models/                  # trained model files (created at runtime)
│   ├── uploads/                 # per-user library files (created at runtime)
│   └── tests/                   # pytest suite (auth, lockout, sessions, offline ML)
└── frontend/
    ├── app.py                   # Flask frontend/proxy (CSRF, hardened cookies)
    ├── templates/
    └── static/
```

## 2. First setup on Windows

Open PowerShell inside the project's root folder (the one that contains `app.py`):

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
copy backend\.env.example backend\.env
notepad backend\.env
```

Fill in at least `FLASK_SECRET_KEY` and `ADMIN_PASSWORD` in `backend\.env` (see section 8).

## 3. Ollama

Install Ollama and make sure `llama3.2` is available:

```powershell
ollama pull llama3.2
ollama serve
```

Keep the `ollama serve` window open while using the AI features.

## 4. Gmail OTP

In `backend\.env` configure a Gmail address and a Google App Password:

```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=yourgmail@gmail.com
SMTP_PASSWORD=your_16_character_google_app_password
SMTP_FROM=yourgmail@gmail.com
```

Do not use your normal Gmail password.

## 5. Gemini image generation

Create a Gemini API key and put it in `backend\.env`:

```env
GEMINI_API_KEY=your_real_key
GEMINI_IMAGE_MODEL=gemini-3.1-flash-image
```

The image model must be available to the Google account/API project you are using.

## 6. Login — one simple screen for everyone

There is a single login page for both Students and Admin — just email + password.
After a correct login, the saved role decides where you land: Students go to `/dashboard`,
the Admin account goes to `/admin`. There is no separate admin login page and nothing extra
to configure — it uses the same `ADMIN_EMAIL` / `ADMIN_PASSWORD` from `backend\.env` (see section 8).

## 7. Start the project — one command

```powershell
python app.py
```

That single command starts Ollama (if installed), the FastAPI backend and the website,
and opens http://127.0.0.1:5000 in your browser. (Double-clicking `backend\start_all.bat` runs the same thing.)
The first run trains the ML model, which can take about a minute.

You only ever open **http://127.0.0.1:5000** — the backend (port 8000) is internal.

### Use it on your phone
1. Put `LAN_ACCESS=true` in `backend\.env` and run `python app.py`.
2. The terminal prints a line like `Phone: http://192.168.1.23:5000`. Open that on your phone (same Wi-Fi).
3. Sign in with the same email + password on the phone. Optionally use "Add to Home screen" for an app-like icon.

## 8. Default admin

Set these before first backend startup if you want a custom admin:

```env
ADMIN_EMAIL=admin@smartplacement.local
ADMIN_PASSWORD=ChangeThisAdminPassword123!
```

The admin account is created in SQLite on first initialization. Change the password before real deployment.

## 9. Running the tests

The backend has an automated test suite that never touches your real database,
your real email, or the internet -- it spins up an isolated copy of the app for
each test.

```powershell
pip install -r backend\requirements.txt
pytest backend
```

(Or `cd backend` first and just run `pytest`.)

This checks the full register → verify → login flow, OTP lockout after too
many wrong guesses, that logging out / resetting your password / an admin
disabling you all immediately invalidate your session, admin-only access
control, and that placement prediction still works even when the dataset
can't be downloaded (offline fallback).

## 10. Security notes

- Keep `backend\.env` private, and set your own `FLASK_SECRET_KEY` (see the generation command in `backend\.env.example`) -- the app will warn on startup if you don't, and will refuse to start at all with `FLASK_ENV=production` and no real `FLASK_SECRET_KEY`.
- Never commit API keys or SMTP passwords to GitHub.
- Set a strong, unique `ADMIN_PASSWORD` in `backend\.env` before first run -- a well-known default admin password is rejected with a startup warning.
- Login sessions now persist in SQLite (not memory), expire after `SESSION_TTL_DAYS` (default 7), and are immediately revoked on logout, password reset, or an admin disabling the account.
- OTPs lock out after `MAX_OTP_ATTEMPTS` (default 5) wrong guesses; request a new one if that happens.
- Every auth endpoint (register, login, verify, forgot, reset) and the AI endpoints (assistant, search, image generation) are rate-limited per IP address to blunt brute-force and abuse.
- All `/api/*` POST requests from the browser require a matching CSRF token (handled automatically by the UI); cookies are `HttpOnly`, `SameSite=Lax`, and `Secure` once `FLASK_ENV=production`.
- For a real deployment beyond local/BCA use, also add: HTTPS/TLS termination, a proper reverse proxy, structured logging/monitoring, and a managed secrets store (the above closes the biggest gaps but a production rollout deserves a full security review).
- Placement probability is an ML estimate, not a guarantee of employment.

## 10. Quick diagnostics before testing

From the project root, run:

```powershell
python diagnose_project.py
```

This checks required files, installed dependencies, presence of `backend\\.env`, and whether the main ports are occupied. It never prints secret values. A port reported as in use may simply mean the application is already running.

Then run the automated tests:

```powershell
pytest backend
```

The single all-in-one `smart_placement` agent is the current design. Unknown/legacy agent IDs now safely fall back to that agent instead of raising a server error. OTPs are generated using Python's cryptographically secure `secrets` generator.
