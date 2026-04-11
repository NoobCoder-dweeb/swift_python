/* ============================================
   Project Swift Admin Panel - Shared Scripts
   ============================================ */

document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    initSidebar();
    initTabs();
    rewriteRecordDetailLinks();
    initNotifications();
});

// Notifications: poll drafts API and show notification when new pending drafts arrive
let _lastDraftCount = 0;
function initNotifications(pollInterval = 5000) {
    const dot = document.getElementById('notificationDot');
    const notifyBtn = document.getElementById('notifyBtn');
    if (!dot || !notifyBtn) {
        // try to fetch dynamically later
        setTimeout(() => initNotifications(pollInterval), 1000);
        return;
    }

    async function check() {
        try {
            const res = await fetch('/api/drafts');
            if (!res.ok) return;
            const drafts = await res.json();
            const pending = drafts.filter(d => d.status === 'pending').length;
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
        } catch (e) {
            // ignore
        }
    }

    check();
    setInterval(check, pollInterval);
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

function rewriteRecordDetailLinks() {
    document.querySelectorAll('a[href$="record-details.html"], a.record-id').forEach(link => {
        const id = (link.textContent || '').trim();
        if (id.startsWith('REC-')) {
            link.setAttribute('href', `/record-details.html?record_id=${encodeURIComponent(id)}`);
        }
    });
}
