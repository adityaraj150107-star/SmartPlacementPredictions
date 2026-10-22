(function(){
  const links=[...document.querySelectorAll('.side-link[data-page]')];
  const sections=[...document.querySelectorAll('.page-section')];
  const title=document.getElementById('pageTitle');
  const nav=document.getElementById('sideNav');
  const backdrop=document.getElementById('sideBackdrop');
  const names={ai:'AI Agent',dashboard:'Dashboard',prediction:'ML Prediction',student:'Student Information',opportunities:'Company Opportunities',resume:'Resume Analyzer',courses:'Courses & Skills',projects:'Projects & Reports',library:'My Library',notifications:'Notifications',about:'About Smart Placement'};
  function show(page, updateHash=true){
    sections.forEach(s=>s.classList.toggle('active',s.dataset.section===page));
    links.forEach(l=>l.classList.toggle('active',l.dataset.page===page));
    if(title) title.textContent=names[page]||'Smart Placement';
    if(updateHash) history.replaceState(null,'','#'+page);
    nav?.classList.remove('open'); backdrop?.classList.remove('show');
    window.scrollTo({top:0,behavior:'smooth'});
    if(page==='student' && typeof loadProfile==='function') loadProfile(); if(page==='notifications' && typeof loadNotifications==='function') loadNotifications();
  }
  links.forEach(l=>l.addEventListener('click',()=>show(l.dataset.page)));
  document.getElementById('mobileMenu')?.addEventListener('click',()=>{if(window.matchMedia('(max-width: 780px)').matches){nav?.classList.add('open');backdrop?.classList.add('show')}else{document.body.classList.toggle('sidebar-collapsed');}});
  document.getElementById('sideClose')?.addEventListener('click',()=>{nav?.classList.remove('open');backdrop?.classList.remove('show')});
  backdrop?.addEventListener('click',()=>{nav?.classList.remove('open');backdrop?.classList.remove('show')});

  // Mobile swipe navigation: swipe right from the left edge to open the menu,
  // and swipe left while the menu is open to close it. Vertical scrolling is preserved.
  let touchStartX=0, touchStartY=0, touchStartTime=0;
  const openMenu=()=>{ if(window.matchMedia('(max-width: 780px)').matches){nav?.classList.add('open');backdrop?.classList.add('show');} };
  const closeMenu=()=>{nav?.classList.remove('open');backdrop?.classList.remove('show');};
  document.addEventListener('touchstart',e=>{
    if(!e.touches || e.touches.length!==1) return;
    touchStartX=e.touches[0].clientX; touchStartY=e.touches[0].clientY; touchStartTime=Date.now();
  },{passive:true});
  document.addEventListener('touchend',e=>{
    if(!e.changedTouches || e.changedTouches.length!==1) return;
    const dx=e.changedTouches[0].clientX-touchStartX;
    const dy=e.changedTouches[0].clientY-touchStartY;
    if(Math.abs(dx)<65 || Math.abs(dx)<Math.abs(dy)*1.25 || Date.now()-touchStartTime>700) return;
    if(!window.matchMedia('(max-width: 780px)').matches) return;
    if(dx>0 && touchStartX<35 && !nav?.classList.contains('open')) openMenu();
    else if(dx<0 && nav?.classList.contains('open')) closeMenu();
  },{passive:true});
  // Make the sidebar itself independently scrollable on shorter phone screens.
  nav?.addEventListener('keydown',e=>{if(e.key==='Escape') closeMenu();});
  document.addEventListener('keydown',e=>{if(e.key==='Escape') closeMenu();});

  document.querySelectorAll('[data-ai-prompt]').forEach(b=>b.addEventListener('click',()=>{show('ai'); const input=document.getElementById('hubInput'); if(input){input.value=b.dataset.aiPrompt; input.focus(); input.dispatchEvent(new Event('input'));}}));
  const initial=(location.hash||'#ai').slice(1); show(names[initial]?initial:'ai',false);
})();
