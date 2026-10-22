const $ = (id) => document.getElementById(id);

function csrfToken() {
  return document.querySelector('meta[name="csrf-token"]')?.content || '';
}

async function req(url, opts = {}) {
  // Auth lives entirely in the httpOnly session cookie now (sent automatically),
  // so the only header we add ourselves is the CSRF token for unsafe methods.
  const method = (opts.method || 'GET').toUpperCase();
  const headers = opts.body instanceof FormData ? {} : {'Content-Type': 'application/json'};
  if (method !== 'GET' && method !== 'HEAD') headers['X-CSRF-Token'] = csrfToken();
  const response = await fetch(url, {...opts, credentials: 'same-origin', headers: {...headers, ...(opts.headers || {})}});
  const body = await response.json().catch(() => ({detail: 'Invalid server response'}));
  if (!response.ok) {
    let detail = body.detail || body.message || 'Request failed';
    if (Array.isArray(detail)) detail = detail.map(x => x.msg || JSON.stringify(x)).join('\n');
    throw new Error(String(detail));
  }
  return body;
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
}

function notify(text, type = 'error') {
  const box = $('msg');
  if (!box) return;
  box.textContent = text;
  box.className = `form-message ${type}`;
  box.classList.remove('hidden');
}

function setBusy(button, busy, text = 'Please wait…') {
  if (!button) return;
  if (busy) {
    button.dataset.original = button.innerHTML;
    button.disabled = true;
    button.innerHTML = `<span class="spinner"></span>${text}`;
  } else {
    button.disabled = false;
    button.innerHTML = button.dataset.original || 'Continue';
  }
}

async function login(event) {
  event?.preventDefault();
  const button = $('loginBtn');
  try {
    setBusy(button, true, 'Signing in…');
    const body = await req('/api/login', {
      method: 'POST',
      body: JSON.stringify({email: $('email').value.trim(), password: $('password').value})
    });
    saveCurrentAccount(body.user);
    notify('Login successful. Opening your dashboard…', 'success');
    setTimeout(() => location.href = body.user.role === 'admin' ? '/admin' : '/dashboard', 350);
  } catch (error) {
    notify(error.message);
    setBusy(button, false);
  }
}

async function registerUser(event) {
  event?.preventDefault();
  const button = $('registerBtn');
  try {
    setBusy(button, true, 'Creating account…');
    await req('/api/register', {
      method: 'POST',
      body: JSON.stringify({name: $('name').value.trim(), email: $('email').value.trim(), password: $('password').value})
    });
    $('registerPane').classList.add('hide');
    $('verifyPanel').classList.add('show');
    $('verifyPanel').setAttribute('aria-hidden','false');
    $('verifyEmail').textContent = $('email').value.trim();
    $('regStep1').classList.remove('active'); $('regStep1').classList.add('done');
    $('regStep2').classList.add('active');
    setTimeout(() => $('otp')?.focus(), 120);
    notify('OTP sent to your email. Continue to the verification step.', 'success');
  } catch (error) {
    notify(error.message);
  } finally {
    setBusy(button, false);
  }
}

function backToRegister(){
  $('verifyPanel')?.classList.remove('show');
  $('verifyPanel')?.setAttribute('aria-hidden','true');
  $('registerPane')?.classList.remove('hide');
  $('regStep1')?.classList.remove('done'); $('regStep1')?.classList.add('active');
  $('regStep2')?.classList.remove('active');
}

async function verifyUser(event) {
  event?.preventDefault();
  try {
    const otp = $('otp').value.trim();
    if (!/^[0-9]{6}$/.test(otp)) throw new Error('Please enter the 6-digit OTP sent to this email.');
    await req('/api/verify', {method: 'POST', body: JSON.stringify({email: $('email').value.trim(), otp})});
    notify('Email verified. You can now sign in.', 'success');
    setTimeout(() => location.href = '/', 700);
  } catch (error) { notify(error.message); }
}

async function resendRegistrationOtp() {
  const button = $('resendOtpBtn');
  try {
    setBusy(button, true, 'Sending OTP…');
    const body = await req('/api/resend-registration-otp', {method:'POST', body:JSON.stringify({email:$('email').value.trim()})});
    notify(body.message || 'A new OTP was sent to your email.', 'success');
  } catch (error) { notify(error.message); }
  finally { setBusy(button, false); }
}

async function forgot() {
  const email = prompt('Enter your registered email address:');
  if (!email) return;
  try {
    const body = await req('/api/forgot', {method:'POST', body:JSON.stringify({email: email.trim()})});
    alert(body.message);
  } catch (error) { alert(error.message); }
}

document.addEventListener('DOMContentLoaded',()=>{const email=document.querySelector('[data-user-email]')?.textContent;const name=document.querySelector('[data-user-name]')?.textContent;if(email)saveCurrentAccount({name,email,role:'student'});if($('accountModal'))$('accountModal').addEventListener('click',e=>{if(e.target.id==='accountModal')closeAccountLogin();});if($('algorithm'))$('algorithm').addEventListener('change',()=>{const v=$('algorithm').value;if($('selectedAlgorithmChip'))$('selectedAlgorithmChip').textContent=v==='random_forest'?'RF':v==='logistic_regression'?'LR':v==='decision_tree'?'DT':'SVM';});if($('accuracyHistory'))loadAccuracyHistory();if($('predictionHistory'))loadPredictionHistory();});

async function logout() {
  await req('/api/logout', {method: 'POST'}).catch(() => {});
  location.href = '/';
}

function showToast(text, type='info') {
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = text;
  document.body.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add('show'));
  setTimeout(() => { toast.classList.remove('show'); setTimeout(() => toast.remove(), 250); }, 3200);
}

async function predict() {
  const button = $('predictBtn');
  try {
    setBusy(button, true, 'Analyzing profile…');
    const body = await req('/api/predict', {method:'POST', body:JSON.stringify({
      cgpa:+$('cgpa').value, tenth:+$('tenth').value, twelfth:+$('twelfth').value,
      aptitude:+$('aptitude').value, mba_score:+$('mba').value, internship:+$('internship').value, course:$('course')?.value || 'BCA',
      hsc_stream:$('hsc_stream').value, degree_type:$('degree_type').value, specialisation:$('specialisation').value, algorithm:$('algorithm')?.value || 'random_forest'
    })});
    renderPrediction(body);
  } catch (error) { showToast(error.message, 'error'); }
  finally { setBusy(button, false); }
}

function renderPrediction(body) {
  const result = $('predictionResult');
  if (!result) return;
  result.classList.remove('hidden');
  const score = Math.round(Number(body.probability));
  $('predictionScore').textContent = `${score}%`;
  $('predictionCircle').style.setProperty('--score', `${score * 3.6}deg`);
  $('predictionStatus').textContent = body.status;
  $('predictionTips').innerHTML = body.tips.map(t => `<li>${escapeHtml(t)}</li>`).join('');
  $('predictionMeta').textContent = `${body.model} • ${body.dataset}`;
  if($('selectedAlgorithmChip')) $('selectedAlgorithmChip').textContent = body.algorithm_key === 'random_forest' ? 'RF' : body.algorithm_key === 'logistic_regression' ? 'LR' : body.algorithm_key === 'decision_tree' ? 'DT' : 'SVM';
  result.scrollIntoView({behavior:'smooth', block:'nearest'});
  loadPredictionHistory();
}


async function evaluateAlgorithms(){
  const button=$('evaluateBtn');
  try{setBusy(button,true,'Evaluating 4 algorithms…');const body=await req('/api/ml/evaluate',{method:'POST',body:JSON.stringify({})});renderAccuracyResults(body.results||[]);showToast('Accuracy evaluation completed and saved to history.','success');}
  catch(e){showToast(e.message,'error');}finally{setBusy(button,false);}
}

async function loadPredictionHistory(){
  const el=$('predictionHistory');if(!el)return;
  try{const body=await req('/api/ml/prediction-history',{method:'GET'});const rows=body.history||[];
    if(!rows.length){el.innerHTML='<div class="muted">No predictions yet. Run a prediction above.</div>';renderPredictionChart([]);return;}
    renderPredictionChart(rows);
    el.innerHTML=`<table class="history-table"><thead><tr><th>Algorithm</th><th>Probability</th><th>Status</th><th>Course</th><th>CGPA</th><th>10th</th><th>12th</th><th>Date</th></tr></thead><tbody>${rows.map(r=>`<tr><td><b>${escapeHtml(r.algorithm)}</b></td><td><strong>${Number(r.probability).toFixed(1)}%</strong></td><td>${escapeHtml(r.status)}</td><td>${escapeHtml(r.course||'—')}</td><td>${r.cgpa??'—'}</td><td>${r.tenth??'—'}%</td><td>${r.twelfth??'—'}%</td><td>${escapeHtml(new Date(r.created_at).toLocaleString())}</td></tr>`).join('')}</tbody></table>`;
  }catch(e){el.innerHTML=`<div class="error-box">${escapeHtml(e.message)}</div>`;}
}
function renderPredictionChart(rows){
  const el=$('predictionChart');if(!el)return;
  const recent=(rows||[]).slice(0,8).reverse();
  if(!recent.length){el.classList.add('empty-chart');el.textContent='Run a student prediction to create this chart.';return;}
  el.classList.remove('empty-chart');
  el.innerHTML=`<div class="prediction-bars">${recent.map((r,i)=>{const score=Math.max(0,Math.min(100,Number(r.probability)||0));const positive=String(r.status||'').toLowerCase().includes('placed')&&!String(r.status||'').toLowerCase().includes('not placed');return `<div class="prediction-bar-item"><div class="prediction-bar-label"><b>${escapeHtml(r.algorithm||'ML Model')}</b><span>${score.toFixed(1)}%</span></div><div class="prediction-bar-track"><i class="${positive?'positive':''}" style="width:${score}%"></i></div><small>${escapeHtml(r.course||'Student')} · ${escapeHtml(r.status||'Prediction')}</small></div>`;}).join('')}</div><p class="chart-footnote">Scores are model estimates, not a guarantee of actual placement.</p>`;
}

function renderAccuracyResults(results){
  const rows=results||[];
  const ids={random_forest:'accRandomForest',logistic_regression:'accLogistic',decision_tree:'accTree',svm:'accSvm'};
  rows.forEach(r=>{const el=$(ids[r.algorithm_key]);if(el)el.textContent=`${Number(r.accuracy).toFixed(2)}%`;});
  renderMetricsChart(rows); renderConfusionMatrices(rows); renderRocChart(rows); loadAccuracyHistory();
}
function renderMetricsChart(rows){
  const el=$('metricsChart'); if(!el)return;
  if(!rows.length){el.classList.add('empty-chart');el.textContent='Run model evaluation to generate this chart.';return;}
  el.classList.remove('empty-chart');
  const metrics=[['accuracy','Accuracy'],['precision','Precision'],['recall','Recall'],['f1','F1-score']];
  el.innerHTML=`<div class="metric-legend">${metrics.map((m,i)=>`<span><i class="metric-dot m${i}"></i>${m[1]}</span>`).join('')}</div><div class="metric-bars">${rows.map(r=>`<div class="metric-model"><b>${escapeHtml(r.algorithm)}</b><div class="metric-bar-stack">${metrics.map((m,i)=>`<div class="metric-bar-row"><span>${m[1]}</span><div class="metric-track"><i class="metric-fill m${i}" style="width:${Math.max(0,Math.min(100,Number(r[m[0]])||0))}%"></i></div><strong>${Number(r[m[0]]).toFixed(1)}%</strong></div>`).join('')}</div></div>`).join('')}</div>`;
}
function renderConfusionMatrices(rows){
  const el=$('confusionCharts');if(!el)return;
  if(!rows.length){el.classList.add('empty-chart');el.textContent='Confusion matrices appear after evaluation.';return;}
  el.classList.remove('empty-chart');
  el.innerHTML=rows.map(r=>{const m=r.confusion_matrix;if(!Array.isArray(m)||m.length!==2)return '';
    const cells=[{v:m[0][0],label:'TN',desc:'Correct not placed'},{v:m[0][1],label:'FP',desc:'False placed'},{v:m[1][0],label:'FN',desc:'Missed placed'},{v:m[1][1],label:'TP',desc:'Correct placed'}];
    return `<div class="confusion-model"><b>${escapeHtml(r.algorithm)}</b><div class="confusion-axis">Actual ↓ · Predicted →</div><div class="confusion-matrix">${cells.map(c=>`<div class="cm-cell cm-${c.label.toLowerCase()}" title="${c.desc}"><small>${c.label}</small><strong>${Number(c.v)}</strong></div>`).join('')}</div><div class="cm-key">TN/TP = correct · FP/FN = errors</div></div>`;
  }).join('');
}
function renderRocChart(rows){
  const el=$('rocChart');if(!el)return;
  const valid=(rows||[]).filter(r=>Array.isArray(r.roc_curve)&&r.roc_curve.length>1);
  if(!valid.length){el.classList.add('empty-chart');el.textContent='ROC curve needs both classes and probability scores in the evaluation split.';return;}
  el.classList.remove('empty-chart');const W=420,H=270,L=42,T=18,R=15,B=35,iw=W-L-R,ih=H-T-B;
  const x=v=>L+Math.max(0,Math.min(1,v))*iw, y=v=>T+(1-Math.max(0,Math.min(1,v)))*ih;
  const colors=['#7c5cff','#28b8ff','#34d399','#fbbf24'];
  const paths=valid.map(r=>{const idx=rows.indexOf(r), pts=r.roc_curve.map(p=>`${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join(' ');return `<polyline points="${pts}" fill="none" stroke="${colors[idx%colors.length]}" stroke-width="2.5" stroke-linejoin="round"/>`;}).join('');
  const grid=[0,.25,.5,.75,1].map(v=>`<line x1="${x(v)}" y1="${T}" x2="${x(v)}" y2="${T+ih}" stroke="#29415b" stroke-dasharray="3 4"/><line x1="${L}" y1="${y(v)}" x2="${L+iw}" y2="${y(v)}" stroke="#29415b" stroke-dasharray="3 4"/><text x="${x(v)}" y="${H-14}" fill="#8ca3bb" font-size="10" text-anchor="middle">${v}</text><text x="${L-8}" y="${y(v)+3}" fill="#8ca3bb" font-size="10" text-anchor="end">${v}</text>`).join('');
  el.innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="ROC curve comparison">${grid}<line x1="${x(0)}" y1="${y(0)}" x2="${x(1)}" y2="${y(1)}" stroke="#64748b" stroke-dasharray="5 5"/>${paths}<text x="${L+iw/2}" y="${H-2}" fill="#a9bdd1" font-size="11" text-anchor="middle">False-positive rate</text><text x="13" y="${T+ih/2}" fill="#a9bdd1" font-size="11" text-anchor="middle" transform="rotate(-90 13 ${T+ih/2})">True-positive rate</text></svg><div class="roc-legend">${valid.map(r=>{const idx=rows.indexOf(r);return `<span><i style="background:${colors[idx%colors.length]}"></i>${escapeHtml(r.algorithm)} · AUC ${r.roc_auc==null?'N/A':Number(r.roc_auc).toFixed(3)}</span>`;}).join('')}</div>`;
}
async function loadAccuracyHistory(){
  const el=$('accuracyHistory');if(!el)return;
  try{const body=await req('/api/ml/history',{method:'GET'});const rows=body.history||[];
    if(!rows.length){el.innerHTML='<div class="muted">No accuracy evaluations saved yet. Click “Find accuracy of all 4 algorithms”.</div>';return;}
    el.innerHTML=`<table class="history-table"><thead><tr><th>Algorithm</th><th>Accuracy</th><th>Precision</th><th>Recall</th><th>F1</th><th>Dataset</th><th>Evaluated</th></tr></thead><tbody>${rows.map(r=>`<tr><td><b>${escapeHtml(r.algorithm)}</b></td><td><strong>${Number(r.accuracy).toFixed(2)}%</strong></td><td>${Number(r.precision).toFixed(2)}%</td><td>${Number(r.recall).toFixed(2)}%</td><td>${Number(r.f1).toFixed(2)}%</td><td>${r.dataset_rows} rows</td><td>${escapeHtml(new Date(r.evaluated_at).toLocaleString())}</td></tr>`).join('')}</tbody></table>`;
  }catch(e){el.innerHTML=`<div class="error-box">${escapeHtml(e.message)}</div>`;}
}

function getSavedAccounts(){try{return JSON.parse(localStorage.getItem('sp_saved_accounts')||'[]');}catch(e){return [];}}
function saveCurrentAccount(user){if(!user?.email)return;const accounts=getSavedAccounts().filter(a=>a.email.toLowerCase()!==user.email.toLowerCase());accounts.unshift({name:user.name,email:user.email,role:user.role});localStorage.setItem('sp_saved_accounts',JSON.stringify(accounts.slice(0,8)));}
function initials(name){return String(name||'SP').trim().split(/\s+/).slice(0,2).map(x=>x[0]).join('').toUpperCase()||'SP';}
function renderAccountMenu(){const menu=$('accountMenu');if(!menu)return;const currentEmail=document.querySelector('[data-user-email]')?.textContent||'';const accounts=getSavedAccounts();menu.innerHTML=`<div class="account-menu-title">Saved accounts</div>${accounts.map(a=>`<button class="saved-account ${a.email.toLowerCase()===currentEmail.toLowerCase()?'current':''}" onclick="openAccountLogin('${encodeURIComponent(a.email)}')"><span class="account-avatar">${escapeHtml(initials(a.name))}</span><span class="account-copy"><b>${escapeHtml(a.name)}</b><small>${escapeHtml(a.email)}</small></span>${a.email.toLowerCase()===currentEmail.toLowerCase()?'<span class="account-check">✓</span>':''}</button>`).join('')}<div class="account-divider"></div><button class="add-account-btn" onclick="openAccountLogin('')"><span>＋</span><b>Add another account</b></button>`;}
function toggleAccountMenu(){const menu=$('accountMenu');if(!menu)return;renderAccountMenu();menu.classList.toggle('hidden');}
function resetAccountModal(){['accountChoiceStep','accountLoginStep','accountCreateStep','accountOtpStep'].forEach(id=>$(id)?.classList.add('hidden'));if($('accountCreateStep'))delete $('accountCreateStep').dataset.started;$('accountChoiceStep')?.classList.remove('hidden');$('accountLoginMsg')?.classList.add('hidden');$('accountLoginOtp').value='';}
function openAccountLogin(emailEncoded=''){const modal=$('accountModal');if(!modal)return;$('accountMenu')?.classList.add('hidden');const email=decodeURIComponent(emailEncoded||'');resetAccountModal();if(email){showAccountSignIn();$('accountLoginEmail').value=email;}modal.classList.remove('hidden');setTimeout(()=>(email?$('accountLoginPassword'):$('accountLoginEmail'))?.focus(),100);}
function closeAccountLogin(){$('accountModal')?.classList.add('hidden');resetAccountModal();}
function showAccountChoice(){resetAccountModal();}
function showAccountSignIn(){['accountChoiceStep','accountCreateStep','accountOtpStep'].forEach(id=>$(id)?.classList.add('hidden'));$('accountLoginStep')?.classList.remove('hidden');$('accountLoginMsg')?.classList.add('hidden');setTimeout(()=>$('accountLoginEmail')?.focus(),80);}
function showAccountCreate(){['accountChoiceStep','accountLoginStep','accountOtpStep'].forEach(id=>$(id)?.classList.add('hidden'));$('accountCreateStep')?.classList.remove('hidden');$('accountCreateStep').dataset.started='0';$('accountLoginMsg')?.classList.add('hidden');setTimeout(()=>$('accountCreateName')?.focus(),80);}
function showAccountMsg(text,type='error'){const msg=$('accountLoginMsg');if(msg){msg.textContent=text;msg.className=`form-message ${type}`;msg.classList.remove('hidden');}}
function finishAccountSwitch(user){saveCurrentAccount(user);closeAccountLogin();showToast(`Switched to ${user.name}.`,'success');setTimeout(()=>location.href=user.role==='admin'?'/admin':'/dashboard',250);}
async function loginAnotherAccount(event){event?.preventDefault();const btn=$('accountLoginBtn');const email=$('accountLoginEmail').value.trim().toLowerCase();const password=$('accountLoginPassword').value;if(!email||!password)return;try{setBusy(btn,true,'Checking account…');const body=await req('/api/account-login-prepare',{method:'POST',body:JSON.stringify({email,password})});if(body.needs_otp){$('accountOtpEmail').textContent=body.email||email;$('accountLoginStep').classList.add('hidden');$('accountCreateStep')?.classList.add('hidden');$('accountOtpStep').classList.remove('hidden');$('accountLoginMsg')?.classList.add('hidden');setTimeout(()=>$('accountLoginOtp')?.focus(),100);showAccountMsg(body.message||'OTP sent to this account email.','success');}else{finishAccountSwitch(body.user);}}catch(e){showAccountMsg(e.message);}finally{setBusy(btn,false);}}
async function createAnotherAccount(event){event?.preventDefault();const btn=$('accountCreateBtn');const name=$('accountCreateName').value.trim();const email=$('accountCreateEmail').value.trim().toLowerCase();const password=$('accountCreatePassword').value;if(!name||!email||password.length<8)return;try{setBusy(btn,true,'Creating account…');const body=await req('/api/account-create-prepare',{method:'POST',body:JSON.stringify({name,email,password})});$('accountCreateStep').dataset.started='1';$('accountOtpEmail').textContent=body.email||email;$('accountCreateStep').classList.add('hidden');$('accountOtpStep').classList.remove('hidden');$('accountLoginMsg')?.classList.add('hidden');showAccountMsg(body.message||'OTP sent to this email.','success');setTimeout(()=>$('accountLoginOtp')?.focus(),100);}catch(e){showAccountMsg(e.message);}finally{setBusy(btn,false);}}
async function verifyAnotherAccount(){const btn=$('accountOtpBtn');const email=($('accountOtpEmail').textContent||$('accountLoginEmail').value).trim().toLowerCase();const otp=$('accountLoginOtp').value.trim();if(!/^[0-9]{6}$/.test(otp))return showAccountMsg('Please enter the 6-digit OTP sent to this account.');const isCreate=!!$('accountCreateStep')?.dataset.started;try{setBusy(btn,true,'Verifying…');let body;if(isCreate){body=await req('/api/account-create-verify',{method:'POST',body:JSON.stringify({email,otp})});}else{body=await req('/api/account-login-verify',{method:'POST',body:JSON.stringify({email,otp})});}finishAccountSwitch(body.user);}catch(e){showAccountMsg(e.message);}finally{setBusy(btn,false);}}
async function resendAnotherAccountOtp(){const btn=$('accountResendBtn');const email=($('accountOtpEmail').textContent||$('accountLoginEmail').value).trim().toLowerCase();const isCreate=!!$('accountCreateStep')?.dataset.started;try{setBusy(btn,true,'Sending OTP…');const path=isCreate?'/api/account-create-resend-otp':'/api/account-login-resend-otp';const body=await req(path,{method:'POST',body:JSON.stringify({email})});showAccountMsg(body.message||'A new OTP was sent.','success');}catch(e){showAccountMsg(e.message);}finally{setBusy(btn,false);}}
function backToAccountLogin(){const createStarted=$('accountCreateStep')?.dataset.started;['accountOtpStep'].forEach(id=>$(id)?.classList.add('hidden'));if(createStarted)showAccountCreate();else showAccountSignIn();$('accountLoginOtp').value='';$('accountLoginMsg')?.classList.add('hidden');}

async function analyzeResume() {
  const file = $('resumeFile')?.files[0];
  if (!file) return showToast('Choose a PDF resume first.', 'error');
  if (file.type !== 'application/pdf') return showToast('Only PDF files are supported.', 'error');
  const button = $('resumeBtn');
  const fd = new FormData(); fd.append('file', file);
  let finishProgress = ()=>{};
  try {
    setBusy(button, true, 'AI reviewing…');
    $('resumeOut').innerHTML='';
    finishProgress = animateResumeProgress();
    const body = await req('/api/resume/analyze', {method:'POST', body:fd});
    finishProgress();
    $('resumeOut').innerHTML = `<div class="resume-preview"><span class="eyebrow">AI REVIEW COMPLETE</span><h3>${escapeHtml(body.filename)}</h3><div class="analysis-text">${escapeHtml(body.feedback || '').replace(/\n/g,'<br>')}</div><details><summary>Extracted text preview</summary><pre>${escapeHtml(body.extracted_preview || '')}</pre></details></div>`;
  } catch (error) { finishProgress(); $('resumeOut').innerHTML = `<div class="error-box">${escapeHtml(error.message)}</div>`; }
  finally { setBusy(button, false); }
}


async function loadRecipients(){
  const select=$('adminRecipient'); if(!select) return;
  try{
    const body=await req('/api/admin/stats',{method:'GET'});
    select.innerHTML='<option value="all">All active students</option>'+body.users.filter(u=>u.role==='student'&&u.active).map(u=>`<option value="${u.id}">${escapeHtml(u.name)} — ${escapeHtml(u.email)}</option>`).join('');
  }catch(e){}
}

async function adminAddStudent(){
  const msg=$('adminStudentMsg');
  try{
    const body=await req('/api/admin/students/create',{method:'POST',body:JSON.stringify({name:$('adminStudentName').value.trim(),email:$('adminStudentEmail').value.trim(),course:$('adminStudentCourse').value,password:$('adminStudentPassword').value})});
    msg.textContent=body.email_sent?'Student created. Account details were emailed to the student.':'Student created, but email could not be sent. Check SMTP configuration.';
    msg.className='form-message success'; msg.classList.remove('hidden');
    $('adminStudentName').value='';$('adminStudentEmail').value='';$('adminStudentPassword').value='';
    loadAdmin();loadRecipients();
  }catch(e){msg.textContent=e.message;msg.className='form-message error';msg.classList.remove('hidden');}
}

async function adminSendMessage(){
  const msg=$('adminMessageMsg');
  try{
    const body=await req('/api/admin/message',{method:'POST',body:JSON.stringify({recipient:$('adminRecipient').value,title:$('adminMessageTitle').value.trim(),message:$('adminMessageBody').value.trim()})});
    msg.textContent=body.message||'Message sent.';msg.className='form-message success';msg.classList.remove('hidden');
    $('adminMessageTitle').value='';$('adminMessageBody').value='';
  }catch(e){msg.textContent=e.message;msg.className='form-message error';msg.classList.remove('hidden');}
}

async function loadNotifications(){
  const el=$('notificationList'); if(!el) return;
  try{
    const body=await req('/api/notifications',{method:'GET'});
    if(!body.notifications.length){el.innerHTML='<p class="muted">No new messages.</p>';return;}
    el.innerHTML=body.notifications.map(n=>`<div class="glass-card info-card" style="margin-bottom:10px"><span class="eyebrow">${escapeHtml(new Date(n.created_at).toLocaleString())}</span><h3>${escapeHtml(n.title)}</h3><p>${escapeHtml(n.message).replace(/\n/g,'<br>')}</p></div>`).join('');
    body.notifications.filter(n=>!n.is_read).forEach(n=>req(`/api/notifications/${n.id}/read`,{method:'POST'}).catch(()=>{}));
  }catch(e){el.innerHTML=`<div class="error-box">${escapeHtml(e.message)}</div>`;}
}

async function loadAdmin() {
  try {
    const body = await req('/api/admin/stats', {method:'GET'});
    const stats = $('stats');
    stats.innerHTML = Object.entries(body.stats).map(([key,value]) => `<div class="stat-card"><span>${escapeHtml(key.replaceAll('_',' '))}</span><strong>${escapeHtml(value)}</strong></div>`).join('');
    $('users').innerHTML = `<div class="table-wrap"><table class="table"><thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Verified</th><th>Active</th><th>Action</th></tr></thead><tbody>${body.users.map(u => `<tr><td>${escapeHtml(u.name)}</td><td>${escapeHtml(u.email)}</td><td><span class="role-chip">${escapeHtml(u.role)}</span></td><td>${u.verified?'Yes':'No'}</td><td>${u.active?'Yes':'No'}</td><td>${u.role==='admin'?'<span class="muted">Protected</span>':`<button class="mini-btn" onclick="toggleUser(${u.id})">${u.active?'Disable':'Enable'}</button>`}</td></tr>`).join('')}</tbody></table></div>`;
  } catch (error) { $('users').innerHTML = `<div class="error-box">${escapeHtml(error.message)}</div>`; }
}

async function toggleUser(id) {
  try { await req(`/api/admin/user/${id}/toggle`, {method:'POST'}); showToast('User status updated.', 'success'); loadAdmin(); }
  catch (error) { showToast(error.message, 'error'); }
}

function previewFile(input) {
  const file = input.files?.[0];
  const label = $('fileName');
  const selected = $('selectedResume');
  const zone = $('resumeDropzone');
  if (!file) { clearResumeFile(); return; }
  if (file.type !== 'application/pdf') { input.value=''; showToast('Please choose a PDF resume.', 'error'); return; }
  if (file.size > 10 * 1024 * 1024) { input.value=''; showToast('PDF must be 10 MB or smaller.', 'error'); return; }
  if (label) label.textContent = file.name;
  selected?.classList.remove('hidden'); zone?.classList.add('hidden');
}

function clearResumeFile(){
  const input=$('resumeFile'); if(input) input.value='';
  $('selectedResume')?.classList.add('hidden');
  $('resumeDropzone')?.classList.remove('hidden');
  $('resumeOut').innerHTML='';
  $('resumeProgress')?.classList.add('hidden');
}

function animateResumeProgress(){
  const box=$('resumeProgress'), bar=$('resumeProgressBar'), pct=$('resumeProgressPct');
  if(!box||!bar||!pct) return ()=>{};
  box.classList.remove('hidden');
  const steps=['resumeStep1','resumeStep2','resumeStep3','resumeStep4'];
  let i=0;
  const timer=setInterval(()=>{
    if(i>0){const prev=$(steps[i-1]); if(prev){prev.classList.remove('active');prev.classList.add('done');prev.textContent='✓ '+prev.textContent.replace(/^. /,'').replace(/^○ /,'');}}
    if(i<steps.length){const el=$(steps[i]); if(el){el.classList.add('active');el.textContent='◉ '+el.textContent.replace(/^. /,'').replace(/^○ /,'');}}
    const value=Math.min(92,20+i*24); bar.style.width=value+'%'; pct.textContent=value+'%'; i++;
    if(i>steps.length) clearInterval(timer);
  },650);
  return ()=>{clearInterval(timer);bar.style.width='100%';pct.textContent='100%';steps.forEach(id=>{const el=$(id);if(el){el.classList.remove('active');el.classList.add('done');el.textContent='✓ '+el.textContent.replace(/^. /,'').replace(/^○ /,'');}})};
}


function initParticles() {
  const canvas = $('particleCanvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  let points = [];
  function resize(){canvas.width=innerWidth;canvas.height=innerHeight;points=Array.from({length:55},()=>({x:Math.random()*canvas.width,y:Math.random()*canvas.height,vx:(Math.random()-.5)*.28,vy:(Math.random()-.5)*.28,r:Math.random()*1.7+.4}));}
  function draw(){ctx.clearRect(0,0,canvas.width,canvas.height);for(const p of points){p.x+=p.vx;p.y+=p.vy;if(p.x<0||p.x>canvas.width)p.vx*=-1;if(p.y<0||p.y>canvas.height)p.vy*=-1;ctx.beginPath();ctx.arc(p.x,p.y,p.r,0,Math.PI*2);ctx.fillStyle='rgba(110,180,255,.35)';ctx.fill();}requestAnimationFrame(draw)}
  resize(); addEventListener('resize',resize); draw();
}

function revealOnScroll() {
  const observer = new IntersectionObserver(entries => entries.forEach(e => e.isIntersecting && e.target.classList.add('visible')), {threshold:.08});
  document.querySelectorAll('.reveal').forEach(el => observer.observe(el));
}

document.addEventListener('DOMContentLoaded', () => {
  const dz=$('resumeDropzone');
  if(dz){
    ['dragenter','dragover'].forEach(ev=>dz.addEventListener(ev,e=>{e.preventDefault();dz.classList.add('dragover');}));
    ['dragleave','drop'].forEach(ev=>dz.addEventListener(ev,e=>{e.preventDefault();dz.classList.remove('dragover');}));
    dz.addEventListener('drop',e=>{const files=e.dataTransfer?.files;if(files?.length){const input=$('resumeFile');input.files=files;previewFile(input);}});
  }

  initParticles();
  revealOnScroll();
  const q = new URLSearchParams(location.search).get('oauth_error');
  if (q) notify(decodeURIComponent(q.replace(/\+/g,' ')));
  // Note: [data-user-name] / [data-user-email] elements are already filled in
  // server-side by Jinja ({{user.name}} / {{user.email}}) on dashboard/admin
  // pages, so there is nothing to hydrate here from client-side storage.
});

// ---------- Student profile ----------
async function loadProfile(){
  if (!$('profileCourse')) return;
  try {
    const body = await req('/api/profile', {method:'GET'});
    const p = body.profile || {};
    const map = {profileName:p.name, profileCourse:p.course, profileSemester:p.semester, profileCollege:p.college, profileCgpa:p.cgpa, profileTenth:p.tenth, profileTwelfth:p.twelfth, profileInternship:String(p.internship ?? 0), profileSkills:p.skills};
    Object.entries(map).forEach(([id,val])=>{ if($(id) && val !== undefined && val !== null) $(id).value=val; });
  } catch(e) { /* profile is optional until first save */ }
}

async function saveProfile(){
  const button=$('profileSaveBtn');
  try{
    setBusy(button,true,'Saving…');
    const body=await req('/api/profile',{method:'POST',body:JSON.stringify({
      name:$('profileName').value.trim(), course:$('profileCourse').value, semester:$('profileSemester').value.trim(),
      college:$('profileCollege').value.trim(), cgpa:$('profileCgpa').value?Number($('profileCgpa').value):null,
      tenth:$('profileTenth').value?Number($('profileTenth').value):null, twelfth:$('profileTwelfth').value?Number($('profileTwelfth').value):null,
      internship:Number($('profileInternship').value), skills:$('profileSkills').value.trim()
    })});
    const box=$('profileMessage');
    if(box){box.textContent=body.message||'Student information saved.';box.className='form-message success';}
  }catch(e){const box=$('profileMessage');if(box){box.textContent=e.message;box.className='form-message error';}}
  finally{setBusy(button,false);}
}

// ---------- Company opportunity matching (guidance only; not live vacancy data) ----------
const opportunityRoles = [
  {company:'TCS',role:'Graduate / Associate IT roles',type:'software',courses:['BCA','MCA','B.Tech','BE','B.Sc','M.Sc'],skills:['programming','problem solving','communication','aptitude','sql'],url:'https://www.tcs.com/careers',summary:'Build programming fundamentals, aptitude and communication; verify each drive’s degree and marks criteria.'},
  {company:'Infosys',role:'Systems / Software roles',type:'software',courses:['BCA','MCA','B.Tech','BE','B.Sc','M.Sc'],skills:['programming','dbms','sql','problem solving','aptitude'],url:'https://www.infosys.com/careers/',summary:'Prepare programming, databases and problem-solving; exact qualifications depend on the posted role.'},
  {company:'Wipro',role:'Graduate / Technology roles',type:'software',courses:['BCA','MCA','B.Tech','BE','B.Sc','M.Sc'],skills:['programming','projects','core cs','communication','sql'],url:'https://careers.wipro.com/',summary:'Showcase relevant projects and technical foundations, and review the exact graduate hiring requirements.'},
  {company:'Accenture',role:'Associate / Analyst roles',type:'business',courses:['BCA','MCA','B.Tech','BE','B.Sc','M.Sc','MBA','BBA','B.Com'],skills:['analytical thinking','communication','digital skills','problem solving','excel'],url:'https://www.accenture.com/in-en/careers',summary:'Explore technology and business roles that fit your degree, analytical ability and listed eligibility.'},
  {company:'HCLTech',role:'Graduate / IT services roles',type:'support',courses:['BCA','MCA','B.Tech','BE','B.Sc','M.Sc'],skills:['technical basics','programming','networking','communication','sql'],url:'https://www.hcltech.com/careers',summary:'Review graduate openings and match your resume to the responsibilities and required skills.'},
  {company:'Cognizant',role:'Software / Data / Support pathways',type:'data',courses:['BCA','MCA','B.Tech','BE','B.Sc','M.Sc'],skills:['sql','programming','data analysis','communication','problem solving'],url:'https://careers.cognizant.com/india-en/',summary:'Choose a specific job family and tailor your projects and resume to its published job description.'},
  {company:'Deloitte',role:'Analyst / Technology pathways',type:'data',courses:['BCA','MCA','B.Tech','BE','B.Sc','M.Sc','MBA','BBA','B.Com'],skills:['data analysis','excel','sql','communication','analytical thinking'],url:'https://www.deloitte.com/in/en/careers.html',summary:'Explore analyst and technology pathways; education and experience requirements differ by role.'},
  {company:'IBM',role:'Associate / Technical pathways',type:'software',courses:['BCA','MCA','B.Tech','BE','B.Sc','M.Sc'],skills:['programming','cloud','sql','problem solving','communication'],url:'https://www.ibm.com/careers',summary:'Develop role-specific technical skills and verify degree, location and experience requirements.'},
  {company:'Capgemini',role:'Graduate / Engineering pathways',type:'testing',courses:['BCA','MCA','B.Tech','BE','B.Sc','M.Sc'],skills:['testing','programming','sql','communication','problem solving'],url:'https://www.capgemini.com/careers/',summary:'Consider software, testing and support roles; apply only if the published eligibility matches your profile.'}
];
function normalizedSkillList(value){return String(value||'').toLowerCase().split(/[,;\n]/).map(s=>s.trim()).filter(Boolean);}
function renderOpportunityMatches(){
  const course=$('oppCourse')?.value||'BCA';
  const interest=$('oppInterest')?.value||'all';
  const skills=normalizedSkillList($('oppSkills')?.value);
  const cgpaRaw=$('oppCgpa')?.value;
  const cgpa=cgpaRaw===''||cgpaRaw==null?null:Number(cgpaRaw);
  const roles=opportunityRoles.filter(r=>(interest==='all'||r.type===interest)&&r.courses.includes(course)).map(r=>{
    const matched=r.skills.filter(req=>skills.some(s=>s.includes(req)||req.includes(s)));
    const skillScore=skills.length?Math.round(matched.length/r.skills.length*100):0;
    const score=skills.length?Math.min(95,Math.round(skillScore*.8+(cgpa===null?10:(cgpa>=7?20:cgpa>=6?12:5)))):null;
    return {...r,matched,score};
  }).sort((a,b)=>(b.score??0)-(a.score??0));
  const root=$('opportunityResults');
  if(!root)return;
  root.innerHTML=roles.map(r=>`<article class="glass-card opportunity-card"><div class="opportunity-card-top"><span class="company-mark">${r.company.slice(0,1)}</span><span class="pill-label">${r.score===null?'Add skills to match':`${r.score}% profile match`}</span></div><div class="opportunity-company">${r.company}</div><h3>${r.role}</h3><p class="muted">${r.summary}</p><div class="match-track"><span style="width:${r.score??0}%"></span></div><div class="skill-tags">${r.skills.map(sk=>`<span class="${r.matched.includes(sk)?'skill-hit':''}">${r.matched.includes(sk)?'✓ ':''}${sk}</span>`).join('')}</div><p class="muted match-footnote">${r.matched.length?`Matched skills: ${r.matched.join(', ')}`:'Add your skills to see which listed role requirements overlap with your profile.'}</p><a href="${r.url}" target="_blank" rel="noopener noreferrer">Official ${r.company} Careers ↗</a></article>`).join('')||'<div class="glass-card info-card"><h3>No matching role examples</h3><p>Try another role category or course.</p></div>';
  const count=$('oppResultCount'); if(count)count.textContent=`${roles.length} role pathways`;
  const status=$('oppProfileStatus'); if(status)status.textContent=skills.length?'Profile matched':'Add skills to personalize';
  const skillsCount=$('oppSkillsCount'); if(skillsCount)skillsCount.textContent=`${skills.length} skill${skills.length===1?'':'s'} listed`;
}
async function useSavedProfileForOpportunities(){
  try{
    const body=await req('/api/profile',{method:'GET'}); const p=body.profile||{};
    if(p.course&&$('oppCourse')){const option=[...$('oppCourse').options].find(o=>o.value.toLowerCase()===String(p.course).toLowerCase());if(option)$('oppCourse').value=option.value;}
    if(p.cgpa!=null&&$('oppCgpa'))$('oppCgpa').value=p.cgpa;
    if(p.skills&&$('oppSkills'))$('oppSkills').value=p.skills;
    renderOpportunityMatches();
    if(typeof notify==='function')notify('Saved student profile loaded for company matching.');
  }catch(e){if(typeof notify==='function')notify('Could not load saved profile. Please complete Student Information first.');}
}
document.addEventListener('DOMContentLoaded',()=>{
  ['findMatchesBtn'].forEach(id=>$(id)?.addEventListener('click',renderOpportunityMatches));
  $('loadProfileMatchesBtn')?.addEventListener('click',useSavedProfileForOpportunities);
  ['oppCourse','oppInterest','oppCgpa','oppSkills'].forEach(id=>$(id)?.addEventListener('change',renderOpportunityMatches));
  $('oppSkills')?.addEventListener('input',renderOpportunityMatches);
  renderOpportunityMatches();
});
