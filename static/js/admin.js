/* ============================================
   Project Swift Admin Panel - Shared Scripts
   ============================================ */

document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    initSidebar();
    initTabs();
    initNotifications();
});

// Notifications: poll drafts API and show notification when new pending drafts arrive
let _lastDraftCount = 0;
let _latestPendingDrafts = [];
function initNotifications(pollInterval = 5000) {
    const dot = document.getElementById('notificationDot');
    const notifyBtn = document.getElementById('notifyBtn');
    if (!dot || !notifyBtn) {
        // try to fetch dynamically later
        setTimeout(() => initNotifications(pollInterval), 1000);
        return;
    }

    const menu = createNotificationMenu();
    notifyBtn.parentElement?.appendChild(menu);

    notifyBtn.addEventListener('click', async (event) => {
        event.stopPropagation();
        if (menu.hidden) {
            await check();
            renderNotificationMenu(menu, _latestPendingDrafts);
            menu.hidden = false;
            notifyBtn.setAttribute('aria-expanded', 'true');
        } else {
            menu.hidden = true;
            notifyBtn.setAttribute('aria-expanded', 'false');
        }
    });

    document.addEventListener('click', (event) => {
        if (menu.hidden) return;
        if (menu.contains(event.target) || notifyBtn.contains(event.target)) return;
        menu.hidden = true;
        notifyBtn.setAttribute('aria-expanded', 'false');
    });

    async function check() {
        try {
            const res = await fetch('/api/drafts');
            if (!res.ok) return;
            const drafts = await res.json();
            const pendingDrafts = drafts.filter(d => d.status === 'pending');
            const pending = pendingDrafts.length;
            _latestPendingDrafts = pendingDrafts;
            if (pending > 0) {
                dot.style.display = 'inline-block';
            } else {
                dot.style.display = 'none';
            }
            if (pending > _lastDraftCount) {
                // simple visual notification
                notifyBtn.classList.add('pulse');
                setTimeout(() => notifyBtn.classList.remove('pulse'), 1200);
            }
            _lastDraftCount = pending;
            renderNotificationMenu(menu, pendingDrafts);
        } catch (e) {
            // ignore
        }
    }

    check();
    setInterval(check, pollInterval);
}

function createNotificationMenu() {
    const menu = document.createElement('div');
    menu.className = 'notification-menu';
    menu.hidden = true;
    menu.innerHTML = `
        <div class="notification-menu-header">
            <div class="notification-menu-title">Pending Drafts</div>
            <div class="notification-menu-count" data-role="count"></div>
        </div>
        <div class="notification-list" data-role="list"></div>
        <div class="notification-menu-footer">
            <span></span>
            <a class="notification-show-all" href="/pending.html">Show All</a>
        </div>
    `;
    return menu;
}

function renderNotificationMenu(menu, drafts) {
    if (!menu) return;
    const count = menu.querySelector('[data-role="count"]');
    const list = menu.querySelector('[data-role="list"]');
    if (!count || !list) return;

    count.textContent = drafts.length === 0 ? 'No pending drafts' : `${drafts.length} pending`;
    const visibleDrafts = drafts.slice(0, 5);

    if (visibleDrafts.length === 0) {
        list.innerHTML = `<div class="notification-empty">No pending drafts right now.</div>`;
        return;
    }

    list.innerHTML = visibleDrafts.map(draft => `
        <a class="notification-item" href="/pending.html">
            <span class="notification-item-subject">${escapeHtml(draft.subject)}</span>
            <span class="notification-item-meta">${escapeHtml(draft.sender)} • ${escapeHtml(draft.created_display || draft.created || '')}</span>
            <span class="notification-item-snippet">${escapeHtml(toSnippet(draft.customer_inquiry || draft.body || ''))}</span>
        </a>
    `).join('');
}

function toSnippet(text, maxLength = 96) {
    const normalized = (text || '').replace(/\s+/g, ' ').trim();
    if (normalized.length <= maxLength) return normalized;
    return normalized.slice(0, maxLength - 1) + '…';
}

function escapeHtml(value) {
    return (value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

/* Theme Toggle */

/* Theme Toggle */
function initTheme() {
    const themeToggle = document.getElementById('themeToggle');
    if (!themeToggle) return;

    const icon = themeToggle.querySelector('i');
    const htmlDoc = document.documentElement;
    const savedTheme = localStorage.getItem('theme') ||
        (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');

    setTheme(savedTheme);

    themeToggle.addEventListener('click', () => {
        const currentTheme = htmlDoc.getAttribute('data-theme');
        const newTheme = currentTheme === 'light' ? 'dark' : 'light';
        setTheme(newTheme);
    });
}

function setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);

    const themeToggle = document.getElementById('themeToggle');
    if (!themeToggle) return;
    const icon = themeToggle.querySelector('i');
    if (theme === 'dark') {
        icon.classList.remove('ph-moon');
        icon.classList.add('ph-sun');
    } else {
        icon.classList.remove('ph-sun');
        icon.classList.add('ph-moon');
    }
}

/* Sidebar */
function initSidebar() {
    const sidebar = document.querySelector('.sidebar');
    const toggleBtn = document.getElementById('sidebarToggle');
    const overlay = document.querySelector('.sidebar-overlay');

    if (!sidebar || !toggleBtn) return;

    toggleBtn.addEventListener('click', () => {
        if (window.innerWidth <= 768) {
            sidebar.classList.toggle('mobile-open');
            overlay.classList.toggle('active');
        } else {
            sidebar.classList.toggle('collapsed');
        }
    });

    if (overlay) {
        overlay.addEventListener('click', () => {
            sidebar.classList.remove('mobile-open');
            overlay.classList.remove('active');
        });
    }

    window.addEventListener('resize', () => {
        if (window.innerWidth > 768) {
            sidebar.classList.remove('mobile-open');
            if (overlay) overlay.classList.remove('active');
        }
    });
}

/* Tabs */
function initTabs() {
    const tabs = document.querySelectorAll('.tab-item');
    const tabPanes = document.querySelectorAll('.tab-pane');

    if (tabs.length === 0) return;

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const targetPane = tab.getAttribute('data-tab');
            tabs.forEach(t => t.classList.remove('active'));
            tabPanes.forEach(p => p.classList.remove('active'));
            tab.classList.add('active');
            if (targetPane) {
                const pane = document.getElementById(targetPane);
                if (pane) pane.classList.add('active');
            }
        });
    });
}
