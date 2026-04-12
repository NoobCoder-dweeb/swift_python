(function(){
  const notificationDot = document.getElementById('notificationDot');
  const draftContainer = document.getElementById('draftContainer');
  const viewToggle = document.getElementById('viewToggle');
  const refreshBtn = document.getElementById('refreshDrafts');
  const recentApproved = new Set();
  const recentRegenerated = new Set();

  function setNotification(visible){
    if(!notificationDot) return;
    notificationDot.style.display = visible ? 'inline-block' : 'none';
  }

  function showToast(message, type='info'){
    let container = document.querySelector('.toasts');
    if(!container){ container = document.createElement('div'); container.className='toasts'; document.body.appendChild(container); }
    const t = document.createElement('div'); t.className = 'toast ' + type; t.textContent = message; container.appendChild(t);
    setTimeout(()=>{ t.style.opacity = '0'; setTimeout(()=>t.remove(),300); }, 3500);
  }

  async function fetchDrafts(){
    try{
      const res = await fetch('/api/drafts');
      const drafts = await res.json();
      setNotification(drafts.length > 0);
      return drafts;
    }catch(e){
      return [];
    }
  }

  async function postAction(url){
    try{
      const res = await fetch(url, {method:'POST', headers:{'X-Requested-With':'XMLHttpRequest','Accept':'application/json'}});
      if(!res.ok) return null;
      const ct = res.headers.get('content-type') || '';
      if(ct.indexOf('application/json') !== -1){
        try{ return await res.json(); }catch(e){ return {}; }
      }
      return {};
    }catch(e){
      return null;
    }
  }

  function createCardFromDraft(d){
    const div = document.createElement('div');
    div.className = 'card draft-card';
    div.dataset.draftId = d.draft_id;
    div.innerHTML = `
      <div class="draft-header">
        <div class="draft-meta">
          <span class="draft-subject">${escapeHtml(d.subject)}</span>
          <span class="draft-sender">From: ${escapeHtml(d.sender)} • ${escapeHtml(d.created_display || d.created)}</span>
        </div>
        <div class="draft-actions">
          <button class="expand-btn" aria-expanded="true"><i class="ph ph-caret-up"></i></button>
          <button class="btn btn-primary approve-btn" data-draft-id="${d.draft_id}">Approve</button>
          <button class="btn btn-secondary reject-btn" data-draft-id="${d.draft_id}">Reject</button>
        </div>
      </div>
      <div class="draft-body">
        <div class="draft-section draft-section-ai">
          <div class="draft-section-label">AI Response Draft</div>
          <div class="draft-section-content">${formatMultiline(d.ai_draft)}</div>
        </div>
        <div class="draft-section">
          <div class="draft-section-label">Customer Inquiry</div>
          <div class="draft-section-content">${formatMultiline(d.customer_inquiry || d.body)}</div>
        </div>
      </div>
    `;
    return div;
  }

  function escapeHtml(s){ return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
  function formatMultiline(s){ return escapeHtml(s).replace(/\n/g, '<br>'); }

  function attachCardHandlers(root=document){
    root.querySelectorAll('.expand-btn').forEach(btn=>{
      if(btn._bound) return; btn._bound = true;
      btn.addEventListener('click', ()=>{
        const card = btn.closest('.draft-card');
        const expanded = !card.classList.toggle('compact');
        btn.setAttribute('aria-expanded', expanded);
        btn.innerHTML = expanded ? '<i class="ph ph-caret-up"></i>' : '<i class="ph ph-caret-down"></i>';
      });
    });
    root.querySelectorAll('.approve-btn').forEach(btn=>{
      if(btn._bound) return; btn._bound = true;
      btn.addEventListener('click', async ()=>{
        const id = btn.dataset.draftId;
        const card = document.querySelector(`.draft-card[data-draft-id='${id}']`);
        const backup = card ? card.outerHTML : null;
        if(card) card.remove();
        showToast('Approving...', 'info');
        const res = await postAction(`/api/drafts/${id}/approve`);
        if(res){
          recentApproved.add(id);
          setTimeout(()=>recentApproved.delete(id),5000);
          showToast('Draft approved', 'success');
        }else{
          showToast('Approve failed', 'error');
          if(backup){ const list = document.getElementById('draftList'); list.insertAdjacentHTML('afterbegin', backup); attachCardHandlers(list); }
        }
      });
    });
    root.querySelectorAll('.reject-btn').forEach(btn=>{
      if(btn._bound) return; btn._bound = true;
      btn.addEventListener('click', async ()=>{
        const id = btn.dataset.draftId;
        const card = document.querySelector(`.draft-card[data-draft-id='${id}']`);
        const backup = card ? card.outerHTML : null;
        if(card) card.remove();
        showToast('Regenerating draft...', 'info');
        const res = await postAction(`/api/drafts/${id}/reject`);
        if(res){
          recentRegenerated.add(id);
          setTimeout(()=>recentRegenerated.delete(id),5000);
          showToast('Draft regenerated', 'error');
        }else{
          showToast('Reject failed', 'error');
          if(backup){ const list = document.getElementById('draftList'); list.insertAdjacentHTML('afterbegin', backup); attachCardHandlers(list); }
        }
      });
    });
  }

  // SSE connection
  if(typeof EventSource !== 'undefined'){
    try{
      const es = new EventSource('/stream');
      es.addEventListener('draft_created', e=>{
        const data = JSON.parse(e.data);
        const list = document.getElementById('draftList');
        if(list){
          const node = createCardFromDraft(data);
          list.insertAdjacentElement('afterbegin', node);
          attachCardHandlers(node);
          setNotification(true);
          showToast('New draft received', 'info');
        }
      });
      es.addEventListener('approved', e=>{
        const data = JSON.parse(e.data);
        const id = data.draft_id || (data.payload && data.payload.draft_id) || data.draftId;
        const card = document.querySelector(`.draft-card[data-draft-id='${id}']`);
        if(card) card.remove();
        if(!recentApproved.has(id)) showToast('Draft approved', 'success');
      });
      es.addEventListener('regenerated', e=>{
        const data = JSON.parse(e.data);
        const draft = data.draft || data.payload || data;
        const list = document.getElementById('draftList');
        if(list && draft){
          const node = createCardFromDraft(draft);
          list.insertAdjacentElement('afterbegin', node);
          attachCardHandlers(node);
          if(!recentRegenerated.has(draft.draft_id)) showToast('Draft regenerated by agent', 'info');
        }
      });
    }catch(e){ console.warn('SSE not available', e); }
  }

  // toggle between expanded (default) and compact
  if(viewToggle){
    viewToggle.addEventListener('click', ()=>{
      const compact = viewToggle.dataset.compact === 'true';
      const list = document.getElementById('draftList');
      if(!list) return;
      list.querySelectorAll('.draft-card').forEach(c=>{
        c.classList.toggle('compact', !compact);
      });
      viewToggle.dataset.compact = (!compact).toString();
      viewToggle.textContent = (!compact) ? 'Expanded View' : 'Compact View';
    });
  }

  if(refreshBtn){ refreshBtn.addEventListener('click', ()=>location.reload()); }

  // initial attach
  attachCardHandlers(document);

  // poll fallback for new drafts and update notification
  setInterval(async ()=>{
    const drafts = await fetchDrafts();
    setNotification(drafts.length > 0);
  }, 10000);
})();
