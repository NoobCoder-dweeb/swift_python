document.addEventListener('DOMContentLoaded', () => {
    initPrioritySelect();
    initTagInput();
    initFormValidation();
    initDatePickers();
    initNumberSteppers();
    initSliders();
});

function initPrioritySelect() {
    const options = document.querySelectorAll('.priority-option');
    options.forEach(option => {
        option.addEventListener('click', () => {
            options.forEach(o => o.classList.remove('selected'));
            option.classList.add('selected');
        });
    });
}

function initTagInput() {
    const tagInput = document.querySelector('.tag-input');
    if (!tagInput) return;

    const input = tagInput.querySelector('input');

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ',') {
            e.preventDefault();
            const value = input.value.trim();
            if (value) {
                addTag(tagInput, value);
                input.value = '';
            }
        }

        if (e.key === 'Backspace' && input.value === '') {
            const lastTag = tagInput.querySelector('.tag-item:last-of-type');
            if (lastTag) lastTag.remove();
        }
    });
}

function addTag(container, text) {
    const tag = document.createElement('span');
    tag.className = 'tag-item';
    tag.innerHTML = text + ' <button type="button">&times;</button>';
    tag.querySelector('button').addEventListener('click', () => tag.remove());
    const input = container.querySelector('input');
    container.insertBefore(tag, input);
}

function initFormValidation() {
    const form = document.getElementById('createRecordForm');
    if (!form) return;

    form.addEventListener('submit', (e) => {
        e.preventDefault();

        const title = form.querySelector('[name="title"]');
        let valid = true;

        clearErrors(form);

        if (!title.value.trim()) {
            showFieldError(title, 'Title is required');
            valid = false;
        }

        if (valid) {
            const overlay = document.createElement('div');
            overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:1000;display:flex;align-items:center;justify-content:center;';
            overlay.innerHTML = `
                <div style="background:var(--surface);padding:2rem;border-radius:var(--radius-md);text-align:center;max-width:360px;box-shadow:var(--shadow-lg);">
                    <div style="font-size:3rem;color:var(--success);margin-bottom:1rem;"><i class="ph ph-check-circle"></i></div>
                    <h3 style="margin-bottom:0.5rem;">Record Created!</h3>
                    <p style="color:var(--text-muted);font-size:0.9rem;margin-bottom:1.5rem;">Your record has been successfully created and is now pending review.</p>
                    <a href="filter-list.html" class="btn btn-primary" style="text-decoration:none;">View Records</a>
                </div>
            `;
            document.body.appendChild(overlay);
        }
    });
}

function showFieldError(input, message) {
    input.classList.add('error');
    const errorEl = document.createElement('div');
    errorEl.className = 'form-error';
    errorEl.textContent = message;
    input.parentNode.appendChild(errorEl);
}

function clearErrors(form) {
    form.querySelectorAll('.form-error').forEach(el => el.remove());
    form.querySelectorAll('.form-input.error').forEach(el => el.classList.remove('error'));
}

function initDatePickers() {
    initDatePicker('startDatePicker', 'startDate', 'startDateDropdown');
    initDatePicker('dueDatePicker', 'dueDate', 'dueDateDropdown');

    const clearBtn = document.getElementById('clearDates');
    if (clearBtn) {
        clearBtn.addEventListener('click', () => {
            document.getElementById('startDate').value = '';
            document.getElementById('dueDate').value = '';
            updateDateRangeBar();
        });
    }
}

function initDatePicker(wrapperId, inputId, dropdownId) {
    const wrapper = document.getElementById(wrapperId);
    const input = document.getElementById(inputId);
    const dropdown = document.getElementById(dropdownId);
    if (!wrapper || !input || !dropdown) return;

    let currentDate = new Date();
    let selectedDate = null;

    const monthNames = ['January', 'February', 'March', 'April', 'May', 'June',
        'July', 'August', 'September', 'October', 'November', 'December'];

    input.addEventListener('click', () => {
        closeAllDropdowns();
        dropdown.classList.add('open');
        renderCalendar(dropdown, currentDate, selectedDate, input, monthNames);
    });

    dropdown.addEventListener('click', (e) => {
        if (e.target.closest('.month-nav-btn')) {
            const dir = e.target.closest('.month-nav-btn').dataset.dir;
            if (dir === 'prev') currentDate.setMonth(currentDate.getMonth() - 1);
            else currentDate.setMonth(currentDate.getMonth() + 1);
            renderCalendar(dropdown, currentDate, selectedDate, input, monthNames);
        }
    });

    document.addEventListener('click', (e) => {
        if (!wrapper.contains(e.target)) {
            dropdown.classList.remove('open');
        }
    });
}

function renderCalendar(dropdown, currentDate, selectedDate, input, monthNames) {
    const grid = dropdown.querySelector('.date-dropdown-grid');
    const label = dropdown.querySelector('.month-label');

    grid.querySelectorAll('.day-cell').forEach(el => el.remove());

    const year = currentDate.getFullYear();
    const month = currentDate.getMonth();
    label.textContent = `${monthNames[month]} ${year}`;

    const firstDay = new Date(year, month, 1).getDay();
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const prevDays = new Date(year, month, 0).getDate();
    const today = new Date();

    for (let x = firstDay; x > 0; x--) {
        const cell = document.createElement('div');
        cell.className = 'day-cell muted';
        cell.textContent = prevDays - x + 1;
        grid.appendChild(cell);
    }

    for (let i = 1; i <= daysInMonth; i++) {
        const cell = document.createElement('div');
        cell.className = 'day-cell';
        cell.textContent = i;

        const isToday = i === today.getDate() && month === today.getMonth() && year === today.getFullYear();
        if (isToday) cell.classList.add('today');

        const inputValue = input.value;
        if (inputValue) {
            const parts = inputValue.split(', ');
            const dateStr = `${monthNames[month]} ${i}, ${year}`;
            if (parts.includes(dateStr)) cell.classList.add('selected');
        }

        cell.addEventListener('click', () => {
            const chosen = new Date(year, month, i);
            input.value = `${monthNames[month]} ${i}, ${year}`;
            input.dispatchEvent(new Event('change'));
            dropdown.classList.remove('open');
            updateDateRangeBar();
        });

        grid.appendChild(cell);
    }

    const totalCells = firstDay + daysInMonth;
    const remaining = (Math.ceil(totalCells / 7) * 7) - totalCells;
    for (let j = 1; j <= remaining; j++) {
        const cell = document.createElement('div');
        cell.className = 'day-cell muted';
        cell.textContent = j;
        grid.appendChild(cell);
    }
}

function updateDateRangeBar() {
    const startInput = document.getElementById('startDate');
    const endInput = document.getElementById('dueDate');
    const bar = document.getElementById('dateRangeBar');
    const durationText = document.getElementById('durationText');

    if (!startInput || !endInput || !bar || !durationText) return;

    if (startInput.value && endInput.value) {
        const start = parseDate(startInput.value);
        const end = parseDate(endInput.value);

        if (start && end) {
            const diffMs = end - start;
            if (diffMs > 0) {
                const diffDays = Math.ceil(diffMs / (1000 * 60 * 60 * 24));
                const daysLabel = diffDays === 1 ? '1 day' : `${diffDays} days`;
                durationText.textContent = `${startInput.value} — ${endInput.value} (${daysLabel})`;
                bar.style.display = 'flex';
                return;
            }
        }
        durationText.textContent = `${startInput.value} — ${endInput.value}`;
        bar.style.display = 'flex';
    } else if (startInput.value || endInput.value) {
        const val = startInput.value || endInput.value;
        durationText.textContent = val;
        bar.style.display = 'flex';
    } else {
        bar.style.display = 'none';
    }
}

function parseDate(str) {
    const monthNames = ['January', 'February', 'March', 'April', 'May', 'June',
        'July', 'August', 'September', 'October', 'November', 'December'];
    const parts = str.replace(',', '').split(' ');
    if (parts.length === 3) {
        const month = monthNames.indexOf(parts[0]);
        const day = parseInt(parts[1]);
        const year = parseInt(parts[2]);
        if (month !== -1 && !isNaN(day) && !isNaN(year)) {
            return new Date(year, month, day);
        }
    }
    return null;
}

function initNumberSteppers() {
    const steppers = document.querySelectorAll('.number-stepper');
    steppers.forEach(stepper => {
        const input = stepper.querySelector('.number-stepper-input');
        const decreaseBtn = stepper.querySelector('.number-stepper-decrease');
        const increaseBtn = stepper.querySelector('.number-stepper-increase');
        if (!input || !decreaseBtn || !increaseBtn) return;

        const step = parseFloat(decreaseBtn.dataset.step) || parseFloat(input.step) || 1;
        const min = parseFloat(decreaseBtn.dataset.min);
        const max = parseFloat(increaseBtn.dataset.max);
        const isCurrency = input.id === 'budgetAmount';

        function formatValue(val) {
            if (isCurrency) {
                return '$' + val.toLocaleString('en-US');
            }
            return val.toString();
        }

        function updateDisplay() {
            let val = parseFloat(input.value) || 0;
            if (!isNaN(min)) val = Math.max(min, val);
            if (!isNaN(max)) val = Math.min(max, val);
            input.value = val;
        }

        decreaseBtn.addEventListener('click', () => {
            let val = parseFloat(input.value) || 0;
            val = val - step;
            if (!isNaN(min)) val = Math.max(min, val);
            input.value = val;
            input.dispatchEvent(new Event('input'));
        });

        increaseBtn.addEventListener('click', () => {
            let val = parseFloat(input.value) || 0;
            val = val + step;
            if (!isNaN(max)) val = Math.min(max, val);
            input.value = val;
            input.dispatchEvent(new Event('input'));
        });

        input.addEventListener('change', () => {
            updateDisplay();
        });
    });
}

function initSliders() {
    const completionSlider = document.getElementById('completionSlider');
    const completionValue = document.getElementById('completionValue');
    const completionFill = document.getElementById('completionFill');

    if (completionSlider) {
        function updateCompletionSlider() {
            const val = parseFloat(completionSlider.value);
            const min = parseFloat(completionSlider.min) || 0;
            const max = parseFloat(completionSlider.max) || 100;
            const pct = ((val - min) / (max - min)) * 100;
            if (completionFill) completionFill.style.width = pct + '%';
            if (completionValue) completionValue.textContent = val + '%';
        }

        completionSlider.addEventListener('input', updateCompletionSlider);
        updateCompletionSlider();
    }

    const prioritySlider = document.getElementById('prioritySlider');
    const prioritySliderValue = document.getElementById('prioritySliderValue');
    const priorityFill = document.getElementById('priorityFill');

    if (prioritySlider) {
        function updatePrioritySlider() {
            const val = parseFloat(prioritySlider.value);
            const min = parseFloat(prioritySlider.min) || 1;
            const max = parseFloat(prioritySlider.max) || 10;
            const pct = ((val - min) / (max - min)) * 100;
            if (priorityFill) priorityFill.style.width = pct + '%';
            if (prioritySliderValue) prioritySliderValue.textContent = val;
        }

        prioritySlider.addEventListener('input', updatePrioritySlider);
        updatePrioritySlider();
    }
}

function closeAllDropdowns() {
    document.querySelectorAll('.date-dropdown.open').forEach(d => d.classList.remove('open'));
}