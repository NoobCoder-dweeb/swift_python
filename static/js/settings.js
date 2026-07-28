document.addEventListener('DOMContentLoaded', () => {
    initSettingsPanels();
    initThemeSettings();
    initPromptSettings();
    initGuardrailSettings();
});

function initSettingsPanels() {
    const tabs = document.querySelectorAll('[data-settings-panel]');
    const panels = document.querySelectorAll('.settings-panel');
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const panelKey = tab.getAttribute('data-settings-panel');
            tabs.forEach(item => item.classList.remove('active'));
            panels.forEach(panel => panel.classList.remove('active'));
            tab.classList.add('active');
            const panel = document.getElementById(`panel-${panelKey}`);
            if (panel) panel.classList.add('active');
        });
    });
}

function initThemeSettings() {
    const options = document.querySelectorAll('[data-theme-choice]');
    const status = document.getElementById('themeStatus');
    if (!options.length) return;

    options.forEach(option => {
        option.addEventListener('click', async () => {
            const theme = option.getAttribute('data-theme-choice');
            setTheme(theme);
            setActiveThemeOption(theme);
            setStatus(status, 'Saving...');
            try {
                const response = await fetch('/api/settings/theme', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({theme}),
                });
                if (!response.ok) throw new Error(await responseText(response));
                setStatus(status, 'Saved');
            } catch (error) {
                setStatus(status, 'Not saved');
                showPromptAlert(error.message || 'Theme could not be saved.', 'danger');
            }
        });
    });
}

function setActiveThemeOption(theme) {
    document.querySelectorAll('[data-theme-choice]').forEach(option => {
        const active = option.getAttribute('data-theme-choice') === theme;
        option.classList.toggle('active', active);
        option.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
}

function initGuardrailSettings() {
    const form = document.getElementById('guardrailsForm');
    const resetBtn = document.getElementById('resetGuardrailsBtn');
    if (!form || form.dataset.canEdit !== 'true') return;

    form.addEventListener('submit', async event => {
        event.preventDefault();
        showGuardrailAlert('Saving guardrail settings...', 'info');
        try {
            const response = await fetch('/api/settings/guardrails', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({rules: collectGuardrailRules()}),
            });
            if (!response.ok) throw new Error(await responseText(response));
            setGuardrailStatus('Customised', true);
            showGuardrailAlert('Guardrail settings saved.', 'success');
        } catch (error) {
            showGuardrailAlert(error.message || 'Guardrail settings could not be saved.', 'danger');
        }
    });

    if (resetBtn) {
        resetBtn.addEventListener('click', async () => {
            if (!window.confirm('Reset guardrail rules to code defaults?')) return;
            showGuardrailAlert('Resetting guardrail settings...', 'info');
            try {
                const response = await fetch('/api/settings/guardrails/reset', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                });
                if (!response.ok) throw new Error(await responseText(response));
                const payload = await response.json();
                fillGuardrailRules(payload.rules || []);
                setGuardrailStatus('Default', false);
                showGuardrailAlert('Guardrail settings reset to code defaults.', 'success');
            } catch (error) {
                showGuardrailAlert(error.message || 'Guardrail settings could not be reset.', 'danger');
            }
        });
    }
}

function initPromptSettings() {
    const promptTabs = document.querySelectorAll('[data-prompt-group]');
    const promptSections = document.querySelectorAll('.prompt-group-section');
    const form = document.getElementById('promptsForm');
    const resetBtn = document.getElementById('resetPromptsBtn');

    promptTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const group = tab.getAttribute('data-prompt-group');
            promptTabs.forEach(item => item.classList.remove('active'));
            promptSections.forEach(section => section.classList.remove('active'));
            tab.classList.add('active');
            const section = document.getElementById(`group-${group}`);
            if (section) section.classList.add('active');
        });
    });

    if (!form || form.dataset.canEdit !== 'true') return;

    form.addEventListener('submit', async event => {
        event.preventDefault();
        showPromptAlert('Saving prompt settings...', 'info');
        try {
            const response = await fetch('/api/settings/prompts', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({groups: collectPromptGroups()}),
            });
            if (!response.ok) throw new Error(await responseText(response));
            setPromptStatus('Customised', true);
            showPromptAlert('Prompt settings saved.', 'success');
        } catch (error) {
            showPromptAlert(error.message || 'Prompt settings could not be saved.', 'danger');
        }
    });

    if (resetBtn) {
        resetBtn.addEventListener('click', async () => {
            if (!window.confirm('Reset AI agent and task prompts to config defaults?')) return;
            showPromptAlert('Resetting prompt settings...', 'info');
            try {
                const response = await fetch('/api/settings/prompts/reset', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                });
                if (!response.ok) throw new Error(await responseText(response));
                const payload = await response.json();
                fillPromptGroups(payload.groups || {});
                setPromptStatus('Default', false);
                showPromptAlert('Prompt settings reset to config defaults.', 'success');
            } catch (error) {
                showPromptAlert(error.message || 'Prompt settings could not be reset.', 'danger');
            }
        });
    }
}

function collectPromptGroups() {
    const groups = {};
    document.querySelectorAll('.prompt-group-section[data-group]').forEach(section => {
        const group = section.dataset.group;
        groups[group] = {};
        section.querySelectorAll('[name]').forEach(input => {
            groups[group][input.name] = input.value;
        });
    });
    return groups;
}

function fillPromptGroups(groups) {
    Object.entries(groups).forEach(([group, values]) => {
        const section = document.querySelector(`.prompt-group-section[data-group="${group}"]`);
        if (!section || !values) return;
        Object.entries(values).forEach(([name, value]) => {
            const input = section.querySelector(`[name="${name}"]`);
            if (input) input.value = value || '';
        });
    });
}

function collectGuardrailRules() {
    return Array.from(document.querySelectorAll('.guardrail-card')).map(card => ({
        flag: card.querySelector('[name="flag"]')?.value || '',
        patterns_text: card.querySelector('[name="patterns_text"]')?.value || '',
    }));
}

function fillGuardrailRules(rules) {
    document.querySelectorAll('.guardrail-card').forEach((card, index) => {
        const rule = rules[index];
        if (!rule) return;
        const flag = card.querySelector('[name="flag"]');
        const patterns = card.querySelector('[name="patterns_text"]');
        if (flag) flag.value = rule.flag || '';
        if (patterns) patterns.value = Array.isArray(rule.patterns)
            ? rule.patterns.join('\n')
            : '';
    });
}

function showPromptAlert(message, tone) {
    const slot = document.getElementById('promptsAlert');
    if (!slot) return;
    const icon = tone === 'success' ? 'ph-check-circle' : tone === 'danger' ? 'ph-warning' : 'ph-info';
    slot.innerHTML = `
        <div class="alert alert-${escapeHtml(tone)}">
            <i class="ph ${icon}"></i>
            <div>${escapeHtml(message)}</div>
        </div>
    `;
}

function showGuardrailAlert(message, tone) {
    const slot = document.getElementById('guardrailsAlert');
    if (!slot) return;
    const icon = tone === 'success' ? 'ph-check-circle' : tone === 'danger' ? 'ph-warning' : 'ph-info';
    slot.innerHTML = `
        <div class="alert alert-${escapeHtml(tone)}">
            <i class="ph ${icon}"></i>
            <div>${escapeHtml(message)}</div>
        </div>
    `;
}

function setStatus(element, text) {
    if (element) element.textContent = text;
}

function setPromptStatus(text, customised) {
    const status = document.getElementById('promptStatus');
    if (!status) return;
    status.textContent = text;
    status.classList.toggle('settings-status-warning', customised);
}

function setGuardrailStatus(text, customised) {
    const status = document.getElementById('guardrailStatus');
    if (!status) return;
    status.textContent = text;
    status.classList.toggle('settings-status-warning', customised);
}

async function responseText(response) {
    try {
        const payload = await response.json();
        return payload.detail || 'Request failed.';
    } catch (error) {
        return 'Request failed.';
    }
}

function escapeHtml(value) {
    return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}
