document.addEventListener('DOMContentLoaded', () => {
    initSettingsNav();
    initThemeOptions();
    initColorOptions();
    initToggleSwitches();
});

function initSettingsNav() {
    const navItems = document.querySelectorAll('.settings-nav-item');
    const panels = document.querySelectorAll('.settings-panel');

    navItems.forEach(item => {
        item.addEventListener('click', () => {
            const target = item.getAttribute('data-panel');

            navItems.forEach(n => n.classList.remove('active'));
            panels.forEach(p => p.classList.remove('active'));

            item.classList.add('active');
            const panel = document.getElementById(target);
            if (panel) panel.classList.add('active');
        });
    });
}

function initThemeOptions() {
    const options = document.querySelectorAll('.theme-option');
    options.forEach(option => {
        option.addEventListener('click', () => {
            options.forEach(o => o.classList.remove('active'));
            option.classList.add('active');

            const theme = option.getAttribute('data-theme');
            document.documentElement.setAttribute('data-theme', theme);
            localStorage.setItem('theme', theme);

            const themeToggle = document.getElementById('themeToggle');
            if (themeToggle) {
                const icon = themeToggle.querySelector('i');
                if (theme === 'dark') {
                    icon.classList.remove('ph-moon');
                    icon.classList.add('ph-sun');
                } else {
                    icon.classList.remove('ph-sun');
                    icon.classList.add('ph-moon');
                }
            }
        });
    });

    const currentTheme = localStorage.getItem('theme') || 'light';
    const themeOption = document.querySelector(`.theme-option[data-theme="${currentTheme}"]`);
    if (themeOption) {
        options.forEach(o => o.classList.remove('active'));
        themeOption.classList.add('active');
    }
}

function initColorOptions() {
    const options = document.querySelectorAll('.color-option');
    options.forEach(option => {
        option.addEventListener('click', () => {
            options.forEach(o => o.classList.remove('active'));
            option.classList.add('active');
        });
    });
}

function initToggleSwitches() {
    const switches = document.querySelectorAll('.switch input');
    switches.forEach(sw => {
        sw.addEventListener('change', () => {
            // Visual feedback only for demo
        });
    });
}