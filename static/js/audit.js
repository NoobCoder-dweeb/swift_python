(function(){
  function setEntryExpanded(entry, expanded){
    if (!entry) return;
    entry.classList.toggle('collapsed', !expanded);
    const btn = entry.querySelector('.audit-toggle');
    if (!btn) return;
    btn.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    btn.innerHTML = expanded ? '<i class="ph ph-caret-up"></i>' : '<i class="ph ph-caret-down"></i>';
  }

  function attachAuditToggles(root=document){
    root.querySelectorAll('.audit-toggle').forEach(btn => {
      if (btn._bound) return;
      btn._bound = true;
      btn.addEventListener('click', () => {
        const entry = btn.closest('.audit-entry');
        if (!entry) return;
        const expanded = entry.classList.contains('collapsed');
        setEntryExpanded(entry, expanded);
      });
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    attachAuditToggles(document);

    const viewToggle = document.getElementById('auditViewToggle');
    if(viewToggle){
      viewToggle.addEventListener('click', () => {
        const compact = viewToggle.dataset.compact === 'true';
        document.querySelectorAll('.audit-entry').forEach(entry => {
          setEntryExpanded(entry, compact);
        });
        viewToggle.dataset.compact = compact ? 'false' : 'true';
        viewToggle.textContent = compact ? 'Compact View' : 'Expanded View';
      });
    }
  });
})();
