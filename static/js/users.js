document.addEventListener('DOMContentLoaded', () => {
    initUserSearch();
    initRoleFilter();
    initInviteCard();
});

function initUserSearch() {
    const input = document.getElementById('userSearch');
    if (!input) return;

    input.addEventListener('input', () => {
        const query = input.value.toLowerCase();
        const cards = document.querySelectorAll('.user-card:not(.invite-card-placeholder)');

        cards.forEach(card => {
            const name = card.querySelector('.user-card-name')?.textContent.toLowerCase() || '';
            const email = card.querySelector('.user-card-email')?.textContent.toLowerCase() || '';
            const role = card.querySelector('.user-card-meta-value')?.textContent.toLowerCase() || '';
            card.style.display = (name.includes(query) || email.includes(query) || role.includes(query)) ? '' : 'none';
        });
    });
}

function initRoleFilter() {
    const chips = document.querySelectorAll('.filter-chip');
    chips.forEach(chip => {
        chip.addEventListener('click', () => {
            chips.forEach(c => c.classList.remove('active'));
            chip.classList.add('active');

            const role = chip.getAttribute('data-role');
            const cards = document.querySelectorAll('.user-card:not(.invite-card-placeholder)');

            cards.forEach(card => {
                const cardRole = card.getAttribute('data-role');
                card.style.display = (role === 'all' || cardRole === role) ? '' : 'none';
            });
        });
    });
}

function initInviteCard() {
    const inviteBtn = document.getElementById('inviteUserBtn');
    if (!inviteBtn) return;

    inviteBtn.addEventListener('click', () => {
        const overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:1000;display:flex;align-items:center;justify-content:center;';
        overlay.innerHTML = `
            <div style="background:var(--surface);padding:2rem;border-radius:var(--radius-md);max-width:420px;width:90%;box-shadow:var(--shadow-lg);">
                <h3 style="margin-bottom:0.5rem;">Invite New User</h3>
                <p style="color:var(--text-muted);font-size:0.9rem;margin-bottom:1.5rem;">Send an invitation email to add a new team member.</p>
                <div class="form-group">
                    <label class="form-label">Email Address</label>
                    <input type="email" class="form-input" id="inviteEmail" placeholder="colleague@company.com">
                </div>
                <div class="form-group">
                    <label class="form-label">Role</label>
                    <select class="form-select" id="inviteRole">
                        <option>Viewer</option>
                        <option>Editor</option>
                        <option>Administrator</option>
                    </select>
                </div>
                <div id="inviteStatus" style="font-size:0.85rem;color:var(--text-muted);min-height:1.25rem;"></div>
                <div style="display:flex;gap:1rem;margin-top:1.5rem;justify-content:flex-end;">
                    <button class="btn btn-secondary" id="cancelInviteBtn">Cancel</button>
                    <button class="btn btn-primary" id="sendInviteBtn">Send Invite</button>
                </div>
            </div>
        `;
        document.body.appendChild(overlay);

        overlay.querySelector('#cancelInviteBtn').addEventListener('click', () => overlay.remove());
        overlay.querySelector('#sendInviteBtn').addEventListener('click', async () => {
            const email = overlay.querySelector('#inviteEmail').value.trim();
            const role = overlay.querySelector('#inviteRole').value;
            const status = overlay.querySelector('#inviteStatus');

            if (!email) {
                status.textContent = 'Please enter an email address.';
                status.style.color = 'var(--danger)';
                return;
            }

            status.textContent = 'Sending invite...';
            status.style.color = 'var(--text-muted)';

            try {
                const response = await fetch('/api/users/invite', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email, role })
                });
                const payload = await response.json();
                if (!response.ok) throw new Error(payload.error || 'Invite failed');
                status.textContent = `Invite created for ${payload.email}. Reloading...`;
                status.style.color = 'var(--success)';
                setTimeout(() => window.location.reload(), 700);
            } catch (error) {
                status.textContent = error.message;
                status.style.color = 'var(--danger)';
            }
        });

        overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
    });
}
