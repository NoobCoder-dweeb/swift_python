/* ============================================
   Project Swift Admin Panel - Shared Scripts
   ============================================ */

document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    initSidebar();
    initTabs();
    rewriteRecordDetailLinks();
});

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
