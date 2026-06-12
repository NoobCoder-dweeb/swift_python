(function(){
  const notificationDot = document.getElementById('notificationDot');
  const draftContainer = document.getElementById('draftContainer');
  const viewToggle = document.getElementById('viewToggle');
  const refreshBtn = document.getElementById('refreshDrafts');
  const recentApproved = new Set();
  const recentRegenerated = new Set();
  const sortOrder = ((draftContainer && draftContainer.dataset.sortOrder) || 'desc').toLowerCase();

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
      const res = await fetch(`/api/drafts?order=${encodeURIComponent(sortOrder)}`);
      const drafts = await res.json();
      setNotification(drafts.length > 0);
      return drafts;
    }catch(e){
      return [];
    }
  }

  async function postAction(url){
    return postActionWithBody(url, null);
  }

  async function postActionWithBody(url, body, method='POST'){
    try{
      const headers = {'X-Requested-With':'XMLHttpRequest','Accept':'application/json'};
      const options = {method, headers};
      if(body){
        headers['Content-Type'] = 'application/json';
        options.body = JSON.stringify(body);
      }
      const res = await fetch(url, options);
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
          <button class="expand-btn" type="button" aria-expanded="true"><i class="ph ph-caret-up"></i></button>
          <button class="btn btn-primary approve-btn" data-draft-id="${d.draft_id}">Approve</button>
          <button class="btn btn-secondary reject-btn" data-draft-id="${d.draft_id}">Reject</button>
          <button class="btn btn-secondary edit-btn" type="button" data-draft-id="${d.draft_id}">Edit</button>
          <button class="btn btn-primary save-edit-btn is-hidden" type="button" data-draft-id="${d.draft_id}">Save</button>
          <button class="btn btn-text cancel-edit-btn is-hidden" type="button" data-draft-id="${d.draft_id}">Cancel</button>
        </div>
      </div>
      <div class="draft-body">
        <div class="draft-section">
          <div class="draft-section-label">Customer Email</div>
          <div class="email-meta">
            <div><strong>From:</strong> ${escapeHtml(d.sender)}</div>
            <div><strong>Subject:</strong> ${escapeHtml(d.subject)}</div>
          </div>
          <div class="draft-section-content">${formatMultiline(d.customer_inquiry || d.body)}</div>
        </div>
        <div class="draft-section draft-section-ai">
          <div class="draft-section-label">AI Response Draft</div>
          <div class="email-meta">
            <div><strong>To:</strong> ${escapeHtml(d.sender)}</div>
            <div><strong>Subject:</strong> Re: ${escapeHtml(d.subject)}</div>
          </div>
          <div class="draft-section-content">${formatMultiline(d.ai_draft)}</div>
        </div>
        <div class="draft-section draft-feedback${d.last_rejection_reason ? '' : ' is-hidden'}">
          <div class="draft-section-label">Reviewer Feedback For Regeneration</div>
          <label class="feedback-label" for="feedback-${d.draft_id}">Reason for rejection</label>
          <textarea
            id="feedback-${d.draft_id}"
            class="feedback-input"
            data-feedback-for="${d.draft_id}"
            rows="3"
            placeholder="Explain what is wrong with this draft so the AI can regenerate a better answer."
          >${escapeHtml(d.last_rejection_reason || '')}</textarea>
          <div class="feedback-error" data-feedback-error-for="${d.draft_id}" hidden>
            A rejection reason is required before regenerating this draft.
          </div>
        </div>
      </div>
    `;
    return div;
  }

  function insertDraftCard(node){
    const list = document.getElementById('draftList');
    if(!list || !node) return;
    if(sortOrder === 'asc'){
      list.insertAdjacentElement('beforeend', node);
    }else{
      list.insertAdjacentElement('afterbegin', node);
    }
  }

  function escapeHtml(s){ return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
  function formatMultiline(s){ return escapeHtml(s).replace(/\n/g, '<br>'); }

  function getRejectionReason(id){
    const input = document.querySelector(`[data-feedback-for='${id}']`);
    return input ? input.value.trim() : '';
  }

  function getFeedbackPanel(id){
    return document.querySelector(`.draft-card[data-draft-id='${id}'] .draft-feedback`);
  }

  function getFeedbackError(id){
    return document.querySelector(`[data-feedback-error-for='${id}']`);
  }

  function showFeedbackPanel(id){
    const panel = getFeedbackPanel(id);
    if(!panel) return;
    panel.classList.remove('is-hidden');
  }

  function setFeedbackError(id, message=''){
    const input = document.querySelector(`[data-feedback-for='${id}']`);
    const error = getFeedbackError(id);
    if(input) input.classList.toggle('has-error', Boolean(message));
    if(!error) return;
    error.hidden = !message;
    error.textContent = message || '';
  }

  function getDraftAiContent(card){
    return card.querySelector('.draft-section-ai .draft-section-content');
  }

  function setDraftEditing(card, enabled){
    if(!card) return;
    const aiContent = getDraftAiContent(card);
    const editBtn = card.querySelector('.edit-btn');
    const saveBtn = card.querySelector('.save-edit-btn');
    const cancelBtn = card.querySelector('.cancel-edit-btn');
    if(!aiContent || !editBtn || !saveBtn || !cancelBtn) return;
    aiContent.contentEditable = enabled ? 'true' : 'false';
    aiContent.classList.toggle('editable', enabled);
    aiContent.setAttribute('aria-label', enabled ? 'Editable AI draft response' : 'AI draft response');
    if(enabled){
      card.dataset.originalAiDraft = aiContent.innerText;
      editBtn.classList.add('is-hidden');
      saveBtn.classList.remove('is-hidden');
      cancelBtn.classList.remove('is-hidden');
      aiContent.focus();
    } else {
      editBtn.classList.remove('is-hidden');
      saveBtn.classList.add('is-hidden');
      cancelBtn.classList.add('is-hidden');
    }
  }

  function restoreDraftText(card){
    const aiContent = getDraftAiContent(card);
    if(!aiContent) return;
    aiContent.textContent = card.dataset.originalAiDraft || aiContent.textContent;
  }

  function setCardExpanded(card, expanded){
    if(!card) return;
    card.classList.toggle('compact', !expanded);
    const btn = card.querySelector('.expand-btn');
    if(!btn) return;
    btn.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    btn.innerHTML = expanded ? '<i class="ph ph-caret-up"></i>' : '<i class="ph ph-caret-down"></i>';
  }

  function attachCardHandlers(root=document){
    root.querySelectorAll('.expand-btn').forEach(btn=>{
      if(btn._bound) return; btn._bound = true;
      btn.addEventListener('click', ()=>{
        const card = btn.closest('.draft-card');
        const expanded = card.classList.contains('compact');
        setCardExpanded(card, expanded);
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
        if(res && res.success !== false){
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
        const rejectionReason = getRejectionReason(id);
        showFeedbackPanel(id);
        if(!rejectionReason){
          setFeedbackError(id, 'A rejection reason is required before regenerating this draft.');
          const input = document.querySelector(`[data-feedback-for='${id}']`);
          if(input) input.focus();
          return;
        }
        setFeedbackError(id, '');
        const backup = card ? card.outerHTML : null;
        if(card) card.remove();
        showToast('Regenerating draft...', 'info');
        const res = await postActionWithBody(`/api/drafts/${id}/reject`, {rejection_reason: rejectionReason});
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

    root.querySelectorAll('.edit-btn').forEach(btn=>{
      if(btn._bound) return; btn._bound = true;
      btn.addEventListener('click', ()=>{
        const card = document.querySelector(`.draft-card[data-draft-id='${btn.dataset.draftId}']`);
        setDraftEditing(card, true);
      });
    });

    root.querySelectorAll('.save-edit-btn').forEach(btn=>{
      if(btn._bound) return; btn._bound = true;
      btn.addEventListener('click', async ()=>{
        const id = btn.dataset.draftId;
        const card = document.querySelector(`.draft-card[data-draft-id='${id}']`);
        if(!card){ return; }
        const aiContent = getDraftAiContent(card);
        const updatedText = aiContent ? aiContent.innerText.trim() : '';
        if(!updatedText){
          showToast('Draft text cannot be blank.', 'error');
          return;
        }
        showToast('Saving draft...', 'info');
        const res = await postActionWithBody(`/api/drafts/${id}`, { ai_draft: updatedText }, 'PATCH');
        if(res){
          if(aiContent) aiContent.textContent = updatedText;
          setDraftEditing(card, false);
          showToast('Draft changes saved', 'success');
        } else {
          showToast('Save failed', 'error');
        }
      });
    });

    root.querySelectorAll('.cancel-edit-btn').forEach(btn=>{
      if(btn._bound) return; btn._bound = true;
      btn.addEventListener('click', ()=>{
        const card = document.querySelector(`.draft-card[data-draft-id='${btn.dataset.draftId}']`);
        if(!card){ return; }
        restoreDraftText(card);
        setDraftEditing(card, false);
      });
    });

    root.querySelectorAll('.feedback-input').forEach(input=>{
      if(input._bound) return; input._bound = true;
      input.addEventListener('input', ()=>{
        const id = input.dataset.feedbackFor;
        if(input.value.trim()){
          setFeedbackError(id, '');
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
          insertDraftCard(node);
          attachCardHandlers(node);
          setNotification(true);
          showToast('New draft received', 'info');
        }
      });
      es.addEventListener('draft_updated', e=>{
        const data = JSON.parse(e.data);
        const card = document.querySelector(`.draft-card[data-draft-id='${data.draft_id}']`);
        if(card){
          const aiContent = card.querySelector('.draft-section-ai .draft-section-content');
          if(aiContent){ aiContent.textContent = data.ai_draft || ''; }
          setDraftEditing(card, false);
          showToast('Draft updated', 'info');
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
          insertDraftCard(node);
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
        setCardExpanded(c, compact);
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
