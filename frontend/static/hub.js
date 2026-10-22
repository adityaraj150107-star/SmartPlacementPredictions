/* AI Agent Hub: agents, "+" menu (files, camera, library, image, sketch, search,
   research, visualize). Depends on helpers from app.js: $, req, escapeHtml, showToast. */
(function () {
  if (!document.getElementById('hub')) return;

  const FALLBACK_AGENTS = [{id: 'smart_placement', name: 'Smart Placement AI', icon: '🤖', tagline: 'Project + placement + study assistant', starters: ['Explain the Smart Placement Predictions project in simple Hinglish', 'How does the Random Forest placement prediction work?', 'Prepare important viva questions for this project', 'I am an MCA/MBA student. Make a placement roadmap for me.']}];
  const MODES = {
    search: {label: 'Web search', icon: '🌐', placeholder: 'Search the web…'},
    research: {label: 'Deep research', icon: '🔬', placeholder: 'What should I research in depth?'},
    visualize: {label: 'Visualize', icon: '📊', placeholder: 'Describe the chart, diagram or interactive tool…'},
    image: {label: 'Create image', icon: '🎨', placeholder: 'Describe the image to create…'},
  };
  const MAX_ATTACH = 5;

  let agents = FALLBACK_AGENTS;
  let activeAgent = 'smart_placement';
  let mode = null;
  let attachments = [];
  let busy = false;
  const histories = {};
  const logs = {};

  // Browser-native voice support: no extra backend service is required.
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  let recognition = null;
  let listening = false;
  let voiceReply = localStorage.getItem('sp_voice_reply') !== 'off';
  let lastSpoken = '';

  function setupVoice() {
    const mic = $('voiceBtn'), toggle = $('voiceToggle');
    if (!mic || !toggle) return;
    toggle.textContent = voiceReply ? '🔊' : '🔇';
    toggle.classList.toggle('muted', !voiceReply);
    toggle.title = voiceReply ? 'AI voice response: On' : 'AI voice response: Off';
    if (!SpeechRecognition) {
      mic.disabled = true;
      mic.title = 'Voice input is not supported in this browser';
      mic.style.opacity = '.45';
    } else {
      recognition = new SpeechRecognition();
      recognition.lang = 'en-IN';
      recognition.interimResults = true;
      recognition.continuous = false;
      recognition.maxAlternatives = 1;
      recognition.onstart = () => {
        listening = true; mic.classList.add('listening');
        showVoiceStatus('Listening… speak your question');
      };
      recognition.onresult = e => {
        let finalText = '';
        for (let i = e.resultIndex; i < e.results.length; i++) {
          const part = e.results[i][0].transcript;
          if (e.results[i].isFinal) finalText += part;
          else updateVoiceStatus('Listening: ' + part);
        }
        if (finalText) { input.value = (input.value ? input.value + ' ' : '') + finalText.trim(); autoGrow(); updateVoiceStatus('Voice text ready • Press send'); }
      };
      recognition.onerror = e => {
        const msg = e.error === 'not-allowed' ? 'Microphone permission was blocked.' : 'Could not hear that. Please try again.';
        updateVoiceStatus(msg);
      };
      recognition.onend = () => {
        listening = false; mic.classList.remove('listening');
        setTimeout(() => hideVoiceStatus(), 1800);
      };
    }
    mic.addEventListener('click', () => {
      if (!recognition) return showToast('Voice input needs Chrome or Edge microphone support.', 'error');
      if (listening) { recognition.stop(); return; }
      try { recognition.start(); } catch (_) {}
    });
    toggle.addEventListener('click', () => {
      voiceReply = !voiceReply;
      localStorage.setItem('sp_voice_reply', voiceReply ? 'on' : 'off');
      toggle.textContent = voiceReply ? '🔊' : '🔇';
      toggle.classList.toggle('muted', !voiceReply);
      toggle.title = voiceReply ? 'AI voice response: On' : 'AI voice response: Off';
      if (!voiceReply) window.speechSynthesis?.cancel();
    });
  }

  function showVoiceStatus(text) {
    let el = $('voiceStatus');
    if (!el) {
      el = document.createElement('div'); el.id = 'voiceStatus'; el.className = 'voice-status';
      $('hub').querySelector('.hub-compose').insertAdjacentElement('beforebegin', el);
    }
    el.classList.remove('hidden'); el.textContent = '🎙️ ' + text;
  }
  function updateVoiceStatus(text) { const el = $('voiceStatus'); if (el) { el.textContent = '🎙️ ' + text; el.classList.remove('hidden'); } }
  function hideVoiceStatus() { const el = $('voiceStatus'); if (el) el.classList.add('hidden'); }

  function speak(text) {
    if (!voiceReply || !('speechSynthesis' in window) || !text) return;
    window.speechSynthesis.cancel();
    const plain = String(text).replace(/[#*_`>]/g, ' ').replace(/\[([^\]]+)\]\([^\)]+\)/g, '$1').replace(/\s+/g, ' ').trim();
    lastSpoken = plain;
    const u = new SpeechSynthesisUtterance(plain.slice(0, 7000));
    u.lang = 'en-IN'; u.rate = .96; u.pitch = 1;
    const voices = window.speechSynthesis.getVoices();
    const preferred = voices.find(v => /en-IN/i.test(v.lang)) || voices.find(v => /^en/i.test(v.lang));
    if (preferred) u.voice = preferred;
    window.speechSynthesis.speak(u);
  }

  function addVoiceButton(node, text) {
    if (!text || !node) return;
    const actions = document.createElement('div'); actions.className = 'msg-actions';
    const b = document.createElement('button'); b.type = 'button'; b.className = 'msg-voice'; b.textContent = '🔊 Listen';
    b.onclick = () => speak(text); actions.appendChild(b); node.appendChild(actions);
  }

  const logsBox = $('hubLogs'), input = $('hubInput'), menu = $('plusMenu'), backdrop = $('menuBackdrop');

  // ---------- markdown (escape first, then add a safe subset of formatting) ----------
  function md(src) {
    const blocks = [];
    let s = escapeHtml(src).replace(/```(\w*)\n?([\s\S]*?)```/g, (m, lang, code) => {
      blocks.push(`<pre><code>${code.replace(/\n$/, '')}</code></pre>`);
      return `@@B${blocks.length - 1}@@`;
    });
    s = s.replace(/`([^`\n]+)`/g, '<code>$1</code>')
      .replace(/^#{1,2} (.*)$/gm, '<h3>$1</h3>').replace(/^#{3,6} (.*)$/gm, '<h4>$1</h4>')
      .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
      .replace(/(^|[^*\w])\*([^*\n]+)\*(?!\w)/g, '$1<em>$2</em>')
      .replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
      .replace(/(?:^|\n)((?:[ \t]*[-*•] .+(?:\n|$))+)/g, (m, b) => '\n<ul>' + b.trim().split('\n').map(l => '<li>' + l.replace(/^[ \t]*[-*•] /, '') + '</li>').join('') + '</ul>\n')
      .replace(/(?:^|\n)((?:[ \t]*\d+[.)] .+(?:\n|$))+)/g, (m, b) => '\n<ol>' + b.trim().split('\n').map(l => '<li>' + l.replace(/^[ \t]*\d+[.)] /, '') + '</li>').join('') + '</ol>\n')
      .replace(/(<\/(?:ul|ol|h3|h4)>)\n+/g, '$1').replace(/\n{2,}/g, '<br><br>').replace(/\n/g, '<br>');
    return s.replace(/@@B(\d+)@@/g, (m, i) => blocks[+i]);
  }
  window.__hubMd = md; // exposed for testing

  // ---------- agents ----------
  async function loadAgents() {
    try { agents = (await req('/api/agents')).agents || FALLBACK_AGENTS; } catch (e) { agents = FALLBACK_AGENTS; }
    activeAgent = agents[0]?.id || 'smart_placement';
    ensureLog(activeAgent);
    const log = logs[activeAgent];
    if (log) log.classList.remove('hidden');
  }

  function ensureLog(id) {
    if (logs[id]) return logs[id];
    const agent = agents.find(a => a.id === id) || FALLBACK_AGENTS[0];
    const el = document.createElement('div');
    el.className = 'hub-log';
    el.innerHTML = `<div class="hub-welcome"><div class="hub-welcome-icon">${agent.icon}</div><h3>${escapeHtml(agent.name)}</h3><p>${escapeHtml(agent.tagline)}. Ask about Smart Placement Predictions, ML, resumes, courses, coding, placement preparation, reports or viva. Use <b>+</b> for files, web search, deep research, images and visuals.</p><div class="starters">${(agent.starters || []).map(t => `<button type="button" class="starter" data-text="${escapeHtml(t)}">${escapeHtml(t)}</button>`).join('')}</div></div>`;
    logsBox.appendChild(el);
    histories[id] = histories[id] || [];
    return (logs[id] = el);
  }

  function selectAgent(id) {
    activeAgent = id;
    Object.values(logs).forEach(l => l.classList.add('hidden'));
    ensureLog(id).classList.remove('hidden');
    scrollDown();
  }

  function scrollDown() { logsBox.scrollTop = logsBox.scrollHeight; }

  function addBubble(role, html, agentId = activeAgent) {
    const log = ensureLog(agentId);
    log.querySelector('.hub-welcome')?.remove();
    const node = document.createElement('div');
    node.className = `msg ${role}`;
    node.innerHTML = html;
    log.appendChild(node);
    if (agentId === activeAgent) scrollDown();
    return node;
  }

  // ---------- plus menu ----------
  function openMenu(open) {
    menu.classList.toggle('hidden', !open);
    backdrop.classList.toggle('hidden', !open);
    $('plusBtn').setAttribute('aria-expanded', open);
    $('plusBtn').classList.toggle('open', open);
  }

  function setMode(m) {
    mode = m;
    const pill = $('modePill');
    if (!m) { pill.classList.add('hidden'); input.placeholder = 'Ask anything…'; return; }
    pill.innerHTML = `${MODES[m].icon} ${MODES[m].label} <button type="button" aria-label="Clear mode" id="clearMode">×</button>`;
    pill.classList.remove('hidden');
    input.placeholder = MODES[m].placeholder;
    input.focus();
  }

  menu.addEventListener('click', e => {
    const btn = e.target.closest('button[data-action]');
    if (!btn) return;
    const action = btn.dataset.action;
    openMenu(false);
    if (action === 'files') $('fileInput').click();
    else if (action === 'camera') $('cameraInput').click();
    else if (action === 'library') openLibrary();
    else if (action === 'sketch') openSketch();
    else if (action.startsWith('mode:')) setMode(action.slice(5));
  });
  $('plusBtn').addEventListener('click', () => openMenu(menu.classList.contains('hidden')));
  backdrop.addEventListener('click', () => openMenu(false));
  document.addEventListener('keydown', e => { if (e.key === 'Escape') { openMenu(false); closeModal(); } });
  $('modePill').addEventListener('click', e => { if (e.target.id === 'clearMode') setMode(null); });
  logsBox.addEventListener('click', e => {
    const st = e.target.closest('.starter');
    if (st) { input.value = st.dataset.text; input.focus(); autoGrow(); }
    const ex = e.target.closest('[data-expand]');
    if (ex) ex.closest('.viz').classList.toggle('expanded');
    const dl = e.target.closest('[data-download]');
    if (dl) downloadViz(dl.closest('.viz'));
  });

  // ---------- attachments ----------
  function renderTray() {
    const tray = $('attachTray');
    tray.classList.toggle('hidden', !attachments.length);
    tray.innerHTML = attachments.map((a, i) =>
      `<div class="att">${a.is_image ? `<img src="${escapeHtml(a.url)}" alt="">` : '<span class="att-doc">📄</span>'}<span class="att-name">${escapeHtml(a.filename)}</span><button type="button" data-rm="${i}" aria-label="Remove">×</button></div>`).join('');
  }
  $('attachTray').addEventListener('click', e => {
    const b = e.target.closest('[data-rm]');
    if (b) { attachments.splice(+b.dataset.rm, 1); renderTray(); }
  });

  function addAttachment(item) {
    if (attachments.some(a => a.id === item.id)) return;
    if (attachments.length >= MAX_ATTACH) return showToast(`You can attach up to ${MAX_ATTACH} files.`, 'error');
    attachments.push(item);
    renderTray();
  }

  async function uploadFiles(fileList, source = 'upload') {
    for (const file of Array.from(fileList)) {
      if (attachments.length >= MAX_ATTACH) { showToast(`You can attach up to ${MAX_ATTACH} files.`, 'error'); break; }
      const fd = new FormData();
      fd.append('file', file, file.name);
      fd.append('source', source);
      const chip = addBubble('system', `Uploading ${escapeHtml(file.name)}…`);
      try {
        addAttachment(await req('/api/library/upload', {method: 'POST', body: fd}));
        chip.remove();
      } catch (err) {
        chip.innerHTML = `<span class="error-text">${escapeHtml(file.name)}: ${escapeHtml(err.message)}</span>`;
      }
    }
  }
  $('fileInput').addEventListener('change', e => { uploadFiles(e.target.files); e.target.value = ''; });
  $('cameraInput').addEventListener('change', e => { uploadFiles(e.target.files, 'camera'); e.target.value = ''; });

  // ---------- modal (library + sketch) ----------
  const modal = $('hubModal'), modalBox = $('hubModalBox');
  function openModal(html) { modalBox.innerHTML = html; modal.classList.remove('hidden'); document.body.classList.add('no-scroll'); }
  function closeModal() { modal.classList.add('hidden'); modalBox.innerHTML = ''; document.body.classList.remove('no-scroll'); }
  modal.addEventListener('click', e => { if (e.target === modal || e.target.closest('[data-close]')) closeModal(); });

  async function openLibrary() {
    openModal('<div class="modal-head"><h3>🗂️ Your library</h3><button type="button" class="icon-x" data-close aria-label="Close">×</button></div><div class="lib-grid" id="libGrid"><p class="muted">Loading…</p></div>');
    try {
      const {items} = await req('/api/library');
      const grid = $('libGrid');
      if (!items.length) { grid.innerHTML = '<p class="muted">Nothing here yet. Upload a file, draw a sketch or create an image and it will appear here.</p>'; return; }
      grid.innerHTML = items.map(it => `<div class="lib-item" data-id="${it.id}" tabindex="0">${it.is_image ? `<img loading="lazy" src="${escapeHtml(it.url)}" alt="">` : '<div class="lib-doc">📄</div>'}<span>${escapeHtml(it.filename)}</span><button type="button" class="lib-del" data-del="${it.id}" aria-label="Delete">🗑</button></div>`).join('');
      grid.onclick = async e => {
        const del = e.target.closest('[data-del]');
        if (del) {
          e.stopPropagation();
          try { await req(`/api/library/${del.dataset.del}`, {method: 'DELETE'}); del.closest('.lib-item').remove(); attachments = attachments.filter(a => a.id !== +del.dataset.del); renderTray(); }
          catch (err) { showToast(err.message, 'error'); }
          return;
        }
        const card = e.target.closest('.lib-item');
        if (!card) return;
        const it = items.find(x => x.id === +card.dataset.id);
        addAttachment({id: it.id, filename: it.filename, is_image: it.is_image, url: it.url});
        closeModal();
      };
    } catch (err) { $('libGrid').innerHTML = `<div class="error-box">${escapeHtml(err.message)}</div>`; }
  }

  function openSketch() {
    openModal(`<div class="modal-head"><h3>✏️ Sketch</h3><button type="button" class="icon-x" data-close aria-label="Close">×</button></div>
      <canvas id="sketchCanvas" width="900" height="560" aria-label="Drawing area"></canvas>
      <div class="sketch-tools"><div class="swatches" id="swatches">${['#111827', '#ef4444', '#22c55e', '#3b82f6', '#f59e0b'].map((c, i) => `<button type="button" class="sw${i ? '' : ' on'}" data-color="${c}" style="background:${c}" aria-label="Color ${c}"></button>`).join('')}<button type="button" class="sw eraser" data-color="#ffffff" aria-label="Eraser">⌫</button></div>
      <label class="size">Size <input type="range" id="sketchSize" min="2" max="28" value="5"></label>
      <button type="button" class="mini-btn" id="sketchClear">Clear</button>
      <button type="button" class="action-btn" id="sketchAttach">Attach sketch</button></div>`);
    const cv = $('sketchCanvas'), ctx = cv.getContext('2d');
    ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, cv.width, cv.height);
    ctx.lineCap = ctx.lineJoin = 'round';
    let color = '#111827', drawing = false, last = null, drew = false;
    const pos = e => { const r = cv.getBoundingClientRect(); return {x: (e.clientX - r.left) * cv.width / r.width, y: (e.clientY - r.top) * cv.height / r.height}; };
    cv.addEventListener('pointerdown', e => { drawing = true; last = pos(e); cv.setPointerCapture(e.pointerId); ctx.beginPath(); ctx.fillStyle = color; ctx.arc(last.x, last.y, $('sketchSize').value / 2, 0, 7); ctx.fill(); drew = true; });
    cv.addEventListener('pointermove', e => {
      if (!drawing) return;
      const p = pos(e);
      ctx.strokeStyle = color; ctx.lineWidth = $('sketchSize').value;
      ctx.beginPath(); ctx.moveTo(last.x, last.y); ctx.lineTo(p.x, p.y); ctx.stroke(); last = p;
    });
    ['pointerup', 'pointercancel'].forEach(t => cv.addEventListener(t, () => { drawing = false; }));
    $('swatches').addEventListener('click', e => {
      const b = e.target.closest('.sw'); if (!b) return;
      color = b.dataset.color;
      document.querySelectorAll('#swatches .sw').forEach(x => x.classList.toggle('on', x === b));
    });
    $('sketchClear').onclick = () => { ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, cv.width, cv.height); drew = false; };
    $('sketchAttach').onclick = () => {
      if (!drew) return showToast('Draw something first.', 'error');
      cv.toBlob(blob => { closeModal(); uploadFiles([new File([blob], 'sketch.png', {type: 'image/png'})], 'sketch'); }, 'image/png');
    };
  }

  // ---------- rendering of results ----------
  function sourcesHtml(sources) {
    if (!sources?.length) return '';
    return `<div class="sources">${sources.map((s, i) => `<a href="${escapeHtml(s.url)}" target="_blank" rel="noopener noreferrer"><i>${i + 1}</i>${escapeHtml(s.title || s.url).slice(0, 60)}</a>`).join('')}</div>`;
  }

  function vizHtml(html) {
    const wrap = document.createElement('div');
    wrap.className = 'viz';
    wrap.innerHTML = '<div class="viz-bar"><span>📊 Interactive visual</span><span><button type="button" data-expand>Expand</button><button type="button" data-download>Download</button></span></div>';
    const frame = document.createElement('iframe');
    frame.setAttribute('sandbox', 'allow-scripts'); // no same-origin: generated code can't touch the app or its cookies
    frame.setAttribute('referrerpolicy', 'no-referrer');
    frame.title = 'Generated visual';
    frame.srcdoc = html;
    wrap.appendChild(frame);
    wrap._html = html;
    return wrap;
  }

  function downloadViz(wrap) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([wrap._html], {type: 'text/html'}));
    a.download = 'visual.html';
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 4000);
  }

  // ---------- sending ----------
  function autoGrow() { input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 160) + 'px'; }
  input.addEventListener('input', autoGrow);
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey && window.matchMedia('(pointer:fine)').matches) { e.preventDefault(); send(); }
  });
  $('hubSend').addEventListener('click', send);

  function setBusy(on) { busy = on; $('hubSend').disabled = on; $('hubSend').classList.toggle('busy', on); }

  function setProcessing(node, currentMode) {
    const steps = currentMode === 'research'
      ? ['Understanding your question…','Planning research queries…','Searching reliable sources…','Reading useful results…','Preparing the final report…']
      : currentMode === 'search'
        ? ['Understanding your search…','Searching the web…','Checking useful results…','Preparing the answer…']
        : currentMode === 'visualize'
          ? ['Understanding your request…','Planning the visual…','Generating the interactive result…']
          : ['Understanding your request…','Checking project context…','Generating the response…'];
    let i=0;
    const render=()=>{node.innerHTML=`<span class="typing"><i></i><i></i><i></i></span><span class="loading-note">${escapeHtml(steps[Math.min(i,steps.length-1)])}</span>`;};
    render();
    const timer=setInterval(()=>{i++;render();if(i>=steps.length-1)clearInterval(timer);},900);
    return ()=>clearInterval(timer);
  }

  async function typewriter(node, raw, speed=10) {
    const text=String(raw||'');
    node.innerHTML='';
    let i=0;
    while(i<text.length){
      const chunk=text.slice(i,i+Math.max(1,Math.round(28-(speed/2))));
      i+=chunk.length;
      node.innerHTML=md(text.slice(0,i));
      scrollDown();
      await new Promise(r=>setTimeout(r,speed));
    }
  }

  async function send() {
    if (busy) return;
    const text = input.value.trim();
    const files = attachments.slice();
    if (!text && !files.length) return;
    const agentId = activeAgent, currentMode = mode;
    if (currentMode === 'image' && !text) return showToast('Describe the image you want first.', 'error');

    const attHtml = files.length ? `<div class="msg-atts">${files.map(f => f.is_image ? `<img src="${escapeHtml(f.url)}" alt="">` : `<span>📄 ${escapeHtml(f.filename)}</span>`).join('')}</div>` : '';
    const tag = currentMode ? `<span class="msg-tag">${MODES[currentMode].icon} ${MODES[currentMode].label}</span>` : '';
    addBubble('user', tag + attHtml + (text ? escapeHtml(text).replace(/\n/g, '<br>') : ''), agentId);
    input.value = ''; autoGrow();
    attachments = []; renderTray();
    const loading = addBubble('assistant', '', agentId);
    const stopProcessing = setProcessing(loading, currentMode);
    setBusy(true);
    try {
      if (currentMode === 'image') {
        const body = await req('/api/generate-image', {method: 'POST', body: JSON.stringify({prompt: text})});
        stopProcessing();
        loading.innerHTML = `<div class="generated"><img src="${escapeHtml(body.image_url)}" alt="Generated image"><a class="text-link" href="${escapeHtml(body.image_url)}" target="_blank" rel="noopener">Open full size ↗</a></div>`;
      } else {
        const history = (histories[agentId] || []).slice(-10);
        const payload = {message: text, agent: agentId, mode: currentMode || 'chat', history, attachment_ids: files.map(f => f.id)};
        const body = await req(currentMode === 'research' ? '/api/agent/research' : '/api/agent/chat', {method: 'POST', body: JSON.stringify(payload)});
        stopProcessing();
        if (body.mode === 'visualize') {
          loading.innerHTML = '';
          loading.appendChild(vizHtml(body.html));
        } else {
          const answerText = body.answer || '';
          await typewriter(loading, answerText, currentMode === 'research' ? 6 : 9);
          loading.innerHTML += sourcesHtml(body.sources) + (body.queries?.length ? `<details class="queries"><summary>Searches used</summary>${body.queries.map(q => `<div>• ${escapeHtml(q)}</div>`).join('')}</details>` : '');
          addVoiceButton(loading, answerText);
          if (voiceReply && answerText) speak(answerText);
        }
        const summary = body.answer || '[Created an interactive visual]';
        (histories[agentId] = histories[agentId] || []).push({role: 'user', content: text || '(attachment)'}, {role: 'assistant', content: summary.slice(0, 3000)});
      }
    } catch (err) {
      loading.innerHTML = `<span class="error-text">${escapeHtml(err.message)}</span>`;
    } finally {
      if (typeof stopProcessing === 'function') stopProcessing();
      setBusy(false);
      if (agentId === activeAgent) scrollDown();
    }
  }

  setupVoice();
  loadAgents();
})();
