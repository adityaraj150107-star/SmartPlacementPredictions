def _latest_otp(database, email, purpose='registration'):
    c = database.conn()
    row = c.execute(
        'SELECT otp FROM otps WHERE email=? AND purpose=? ORDER BY id DESC LIMIT 1',
        (email, purpose),
    ).fetchone()
    c.close()
    return row['otp'] if row else None


def _register_and_verify(client, database, email, password='StrongPass123'):
    r = client.post('/auth/register', json={'name': 'Test User', 'email': email, 'password': password})
    assert r.status_code == 200, r.text
    otp = _latest_otp(database, email)
    assert otp is not None
    v = client.post('/auth/verify', json={'email': email, 'otp': otp})
    assert v.status_code == 200, v.text


def test_health(app_client):
    client, main, database, ml_model, sent = app_client
    r = client.get('/health')
    assert r.status_code == 200
    assert r.json()['status'] == 'ok'


def test_register_sends_otp_email(app_client):
    client, main, database, ml_model, sent = app_client
    email = 'newstudent@example.com'
    r = client.post('/auth/register', json={'name': 'New Student', 'email': email, 'password': 'StrongPass123'})
    assert r.status_code == 200, r.text
    assert sent['to'] == email
    assert 'OTP' in sent['subject']


def test_full_register_verify_login_flow(app_client):
    client, main, database, ml_model, sent = app_client
    email = 'flow@example.com'
    _register_and_verify(client, database, email)

    login = client.post('/auth/login', json={'email': email, 'password': 'StrongPass123'})
    assert login.status_code == 200, login.text
    token = login.json()['token']
    assert token

    me = client.get('/auth/session', headers={'Authorization': f'Bearer {token}'})
    assert me.status_code == 200
    assert me.json()['user']['email'] == email


def test_login_rejects_wrong_password(app_client):
    client, main, database, ml_model, sent = app_client
    email = 'wrongpass@example.com'
    _register_and_verify(client, database, email)
    r = client.post('/auth/login', json={'email': email, 'password': 'DefinitelyWrong'})
    assert r.status_code == 401


def test_login_blocked_before_email_verification(app_client):
    client, main, database, ml_model, sent = app_client
    email = 'unverified@example.com'
    client.post('/auth/register', json={'name': 'Unverified', 'email': email, 'password': 'StrongPass123'})
    r = client.post('/auth/login', json={'email': email, 'password': 'StrongPass123'})
    assert r.status_code == 403


def test_otp_lockout_after_max_attempts(app_client):
    # The fixture sets MAX_OTP_ATTEMPTS=3.
    client, main, database, ml_model, sent = app_client
    email = 'lockout@example.com'
    client.post('/auth/register', json={'name': 'Lockout Test', 'email': email, 'password': 'StrongPass123'})

    for _ in range(3):
        r = client.post('/auth/verify', json={'email': email, 'otp': '000000'})
        assert r.status_code in (400, 429)

    # The 3rd wrong guess invalidates the OTP outright (locked out), so any
    # further guess -- even a different one -- is now rejected as expired/gone
    # rather than re-counted, and the user must request a brand new OTP.
    locked = client.post('/auth/verify', json={'email': email, 'otp': '123456'})
    assert locked.status_code == 400
    assert 'new' in locked.json()['detail'].lower()


def test_predict_requires_auth(app_client):
    client, main, database, ml_model, sent = app_client
    r = client.post('/predict', json={
        'cgpa': 8, 'tenth': 80, 'twelfth': 75, 'aptitude': 70, 'mba_score': 65, 'internship': 1,
    })
    assert r.status_code == 401


def test_predict_works_offline_via_fallback_dataset(app_client, monkeypatch):
    """The whole point of the offline fallback dataset: predictions must keep
    working even when the real dataset can't be downloaded (no internet)."""
    client, main, database, ml_model, sent = app_client

    def _always_fails(timeout=30):
        raise OSError('simulated: no network access in test environment')

    monkeypatch.setattr(ml_model, '_download', _always_fails)

    login = client.post('/auth/login', json={'email': 'admin@test.local', 'password': 'TestAdminPass123!'})
    token = login.json()['token']

    r = client.post('/predict', json={
        'cgpa': 8.5, 'tenth': 85, 'twelfth': 80, 'aptitude': 75, 'mba_score': 70, 'internship': 1,
    }, headers={'Authorization': f'Bearer {token}'})
    assert r.status_code == 200, r.text
    body = r.json()
    assert 0 <= body['probability'] <= 100
    assert body['status'] in ('Likely to be Placed', 'Needs Improvement')
    assert isinstance(body['tips'], list)


def test_non_admin_cannot_view_admin_stats(app_client):
    client, main, database, ml_model, sent = app_client
    email = 'student2@example.com'
    _register_and_verify(client, database, email)
    login = client.post('/auth/login', json={'email': email, 'password': 'StrongPass123'})
    token = login.json()['token']

    r = client.get('/admin/stats', headers={'Authorization': f'Bearer {token}'})
    assert r.status_code == 403


def test_admin_login_and_stats(app_client):
    client, main, database, ml_model, sent = app_client
    login = client.post('/auth/login', json={'email': 'admin@test.local', 'password': 'TestAdminPass123!'})
    assert login.status_code == 200
    assert login.json()['user']['role'] == 'admin'
    token = login.json()['token']

    stats = client.get('/admin/stats', headers={'Authorization': f'Bearer {token}'})
    assert stats.status_code == 200
    assert 'students' in stats.json()['stats']


def test_logout_invalidates_the_session_immediately(app_client):
    client, main, database, ml_model, sent = app_client
    email = 'logout@example.com'
    _register_and_verify(client, database, email)
    login = client.post('/auth/login', json={'email': email, 'password': 'StrongPass123'})
    token = login.json()['token']

    still_valid = client.get('/auth/session', headers={'Authorization': f'Bearer {token}'})
    assert still_valid.status_code == 200

    client.post('/auth/logout', headers={'Authorization': f'Bearer {token}'})

    after_logout = client.get('/auth/session', headers={'Authorization': f'Bearer {token}'})
    assert after_logout.status_code == 401


def test_password_reset_invalidates_old_sessions(app_client):
    client, main, database, ml_model, sent = app_client
    email = 'resetme@example.com'
    _register_and_verify(client, database, email)

    login = client.post('/auth/login', json={'email': email, 'password': 'StrongPass123'})
    old_token = login.json()['token']
    assert client.get('/auth/session', headers={'Authorization': f'Bearer {old_token}'}).status_code == 200

    client.post('/auth/forgot', json={'email': email})
    otp = _latest_otp(database, email, purpose='password reset')
    assert otp is not None

    reset = client.post('/auth/reset', json={'email': email, 'otp': otp, 'password': 'BrandNewPass456'})
    assert reset.status_code == 200, reset.text

    # The token issued before the reset must no longer work.
    stale = client.get('/auth/session', headers={'Authorization': f'Bearer {old_token}'})
    assert stale.status_code == 401

    # But the new password logs in fine.
    relogin = client.post('/auth/login', json={'email': email, 'password': 'BrandNewPass456'})
    assert relogin.status_code == 200


def test_admin_disabling_a_student_revokes_their_session(app_client):
    client, main, database, ml_model, sent = app_client
    email = 'disableme@example.com'
    _register_and_verify(client, database, email)
    student_login = client.post('/auth/login', json={'email': email, 'password': 'StrongPass123'})
    student_token = student_login.json()['token']
    student_id = student_login.json()['user']['id']

    admin_login = client.post('/auth/login', json={'email': 'admin@test.local', 'password': 'TestAdminPass123!'})
    admin_token = admin_login.json()['token']

    toggle = client.post(f'/admin/user/{student_id}/toggle', headers={'Authorization': f'Bearer {admin_token}'})
    assert toggle.status_code == 200
    assert toggle.json()['active'] == 0

    blocked = client.get('/auth/session', headers={'Authorization': f'Bearer {student_token}'})
    assert blocked.status_code == 401


# ---------------------------------------------------------------------------
# AI agents, library, Google handoff
# ---------------------------------------------------------------------------
PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 64


def _student_token(client, database, email='agent@example.com'):
    _register_and_verify(client, database, email)
    return client.post('/auth/login', json={'email': email, 'password': 'StrongPass123'}).json()['token']


def _h(token):
    return {'Authorization': f'Bearer {token}'}


def test_agents_list_exposes_single_smart_placement_agent(app_client):
    client, main, database, ml_model, sent = app_client
    token = _student_token(client, database)
    response = client.get('/agents', headers=_h(token))
    assert response.status_code == 200
    agents = response.json()['agents']
    assert len(agents) == 1
    assert agents[0]['id'] == 'smart_placement'
    assert client.get('/agents').status_code == 401


def test_unknown_agent_id_falls_back_to_smart_placement_prompt(app_client, monkeypatch):
    client, main, database, ml_model, sent = app_client
    token = _student_token(client, database, email='unknown-agent@example.com')
    seen = {}

    def fake_llm(system, history, text, images=None):
        seen['system'] = system
        return 'ok'

    monkeypatch.setattr(main.ai, 'call_llm', fake_llm)
    response = client.post('/agent/chat', headers=_h(token), json={
        'message': 'Explain my placement project', 'agent': 'old-agent-id',
    })
    assert response.status_code == 200, response.text
    assert 'SMART PLACEMENT PREDICTIONS' in seen['system']


def test_agent_chat_uses_agent_system_prompt_and_history(app_client, monkeypatch):
    client, main, database, ml_model, sent = app_client
    token = _student_token(client, database)
    seen = {}

    def fake_llm(system, history, text, images=None):
        seen.update(system=system, history=history, text=text, images=images)
        return 'hello from the model'

    monkeypatch.setattr(main.ai, 'call_llm', fake_llm)
    r = client.post('/agent/chat', headers=_h(token), json={
        'message': 'Explain the placement project', 'agent': 'smart_placement',
        'history': [{'role': 'user', 'content': 'hi'}, {'role': 'assistant', 'content': 'hey'}]})
    assert r.status_code == 200 and r.json()['answer'] == 'hello from the model'
    assert 'SMART PLACEMENT PREDICTIONS' in seen['system'] and [h['role'] for h in seen['history']] == ['user', 'assistant']


def test_agent_chat_needs_login_message_or_file_and_valid_mode(app_client, monkeypatch):
    client, main, database, ml_model, sent = app_client
    assert client.post('/agent/chat', json={'message': 'hi'}).status_code == 401
    token = _student_token(client, database)
    assert client.post('/agent/chat', headers=_h(token), json={'message': ''}).status_code == 400
    assert client.post('/agent/chat', headers=_h(token), json={'message': 'x', 'mode': 'hack'}).status_code == 400


def test_llm_unavailable_returns_helpful_503(app_client, monkeypatch):
    client, main, database, ml_model, sent = app_client
    token = _student_token(client, database)

    def boom(*a, **k):
        raise main.ai.LLMUnavailable('No AI model is available. Start Ollama')

    monkeypatch.setattr(main.ai, 'call_llm', boom)
    r = client.post('/agent/chat', headers=_h(token), json={'message': 'hi'})
    assert r.status_code == 503 and 'Ollama' in r.json()['detail']


def test_upload_library_and_attachment_reaches_the_model(app_client, monkeypatch):
    client, main, database, ml_model, sent = app_client
    token = _student_token(client, database)
    up = client.post('/library/upload', headers=_h(token), files={'file': ('notes.txt', b'my secret plan', 'text/plain')})
    assert up.status_code == 200, up.text
    item = up.json()
    lib = client.get('/library', headers=_h(token)).json()['items']
    assert [i['id'] for i in lib] == [item['id']]

    seen = {}
    monkeypatch.setattr(main.ai, 'call_llm', lambda system, history, text, images=None: seen.update(text=text) or 'ok')
    client.post('/agent/chat', headers=_h(token), json={'message': 'summarise', 'attachment_ids': [item['id']]})
    assert 'my secret plan' in seen['text'] and 'notes.txt' in seen['text']


def test_image_attachment_is_passed_as_image_bytes(app_client, monkeypatch):
    client, main, database, ml_model, sent = app_client
    token = _student_token(client, database)
    item = client.post('/library/upload', headers=_h(token), files={'file': ('shot.png', PNG, 'image/png')}).json()
    assert item['is_image'] is True
    seen = {}
    monkeypatch.setattr(main.ai, 'call_llm', lambda system, history, text, images=None: seen.update(images=images) or 'ok')
    client.post('/agent/chat', headers=_h(token), json={'message': 'what is this?', 'attachment_ids': [item['id']]})
    assert seen['images'] and seen['images'][0][0] == 'image/png'


def test_upload_rejects_disguised_executables_and_oversize(app_client):
    client, main, database, ml_model, sent = app_client
    token = _student_token(client, database)
    r = client.post('/library/upload', headers=_h(token), files={'file': ('cute.png', b'MZ\x90\x00 evil', 'image/png')})
    assert r.status_code == 415
    big = client.post('/library/upload', headers=_h(token), files={'file': ('big.txt', b'a' * (9 * 1024 * 1024), 'text/plain')})
    assert big.status_code == 413


def test_users_cannot_read_or_use_each_others_files(app_client, monkeypatch):
    client, main, database, ml_model, sent = app_client
    alice = _student_token(client, database, 'alice@example.com')
    bob = _student_token(client, database, 'bob@example.com')
    item = client.post('/library/upload', headers=_h(alice), files={'file': ('a.png', PNG, 'image/png')}).json()
    assert client.get(f"/library/{item['id']}/file", headers=_h(alice)).status_code == 200
    assert client.get(f"/library/{item['id']}/file", headers=_h(bob)).status_code == 404
    assert client.delete(f"/library/{item['id']}", headers=_h(bob)).status_code == 404
    monkeypatch.setattr(main.ai, 'call_llm', lambda *a, **k: 'ok')
    r = client.post('/agent/chat', headers=_h(bob), json={'message': 'x', 'attachment_ids': [item['id']]})
    assert r.status_code == 404


def test_visualize_returns_html_locked_down_by_csp(app_client, monkeypatch):
    client, main, database, ml_model, sent = app_client
    token = _student_token(client, database)
    monkeypatch.setattr(main.ai, 'call_llm', lambda *a, **k: '```html\n<!doctype html><html><head></head><body><svg></svg></body></html>\n```')
    r = client.post('/agent/chat', headers=_h(token), json={'message': 'bar chart of sales', 'mode': 'visualize'})
    assert r.status_code == 200 and "default-src 'none'" in r.json()['html'] and 'connect-src' in r.json()['html']


def test_web_search_mode_returns_sources(app_client, monkeypatch):
    client, main, database, ml_model, sent = app_client
    token = _student_token(client, database)
    monkeypatch.setattr(main.ai, 'web_search', lambda q, n=6: [{'title': 'Doc', 'url': 'https://example.com/a', 'snippet': 'fact'}])
    monkeypatch.setattr(main.ai, 'call_llm', lambda *a, **k: 'Answer [1]')
    r = client.post('/agent/chat', headers=_h(token), json={'message': 'news', 'mode': 'search'})
    assert r.status_code == 200 and r.json()['sources'][0]['url'] == 'https://example.com/a'


def test_deep_research_plans_queries_and_cites_sources(app_client, monkeypatch):
    client, main, database, ml_model, sent = app_client
    token = _student_token(client, database)
    monkeypatch.setattr(main.ai, 'web_search', lambda q, n=6: [{'title': q, 'url': f'https://example.com/{abs(hash(q)) % 999}', 'snippet': 's'}])
    monkeypatch.setattr(main.ai, 'fetch_page_text', lambda url, **k: 'page text')
    monkeypatch.setattr(main.ai, 'call_llm', lambda system, history, text, images=None: '["query one", "query two"]' if 'JSON array' in text else '# Report [1]')
    r = client.post('/agent/research', headers=_h(token), json={'message': 'future of AI jobs', 'mode': 'research'})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['queries'] == ['query one', 'query two'] and body['sources'] and body['answer'].startswith('# Report')


def test_admin_and_student_use_the_same_login_endpoint(app_client):
    """There is only one login screen/endpoint; the saved role decides where you land."""
    client, main, database, ml_model, sent = app_client
    email = 'sameflow@example.com'
    _register_and_verify(client, database, email)
    student = client.post('/auth/login', json={'email': email, 'password': 'StrongPass123'})
    admin = client.post('/auth/login', json={'email': 'admin@test.local', 'password': 'TestAdminPass123!'})
    assert student.status_code == 200 and student.json()['user']['role'] == 'student'
    assert admin.status_code == 200 and admin.json()['user']['role'] == 'admin'
