(function(){
  function attachAuditToggles(root=document){
    root.querySelectorAll('.audit-toggle').forEach(btn => {
      if (btn._bound) return;
      btn._bound = true;
      btn.addEventListener('click', () => {
        const entry = btn.closest('.audit-entry');
        if (!entry) return;
        const expanded = !entry.classList.toggle('collapsed');
        btn.setAttribute('aria-expanded', expanded ? 'true' : 'false');
        btn.innerHTML = expanded ? '<i class="ph ph-caret-up"></i>' : '<i class="ph ph-caret-down"></i>';
      });
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    attachAuditToggles(document);
  });
})();
