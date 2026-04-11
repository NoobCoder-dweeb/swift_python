document.addEventListener('DOMContentLoaded', () => {
    initCalendar();
    initMiniCalendar();
    initViewToggle();
    initUpcomingClicks();
});

const MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December'];
const DAY_NAMES = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const DAY_ABBR = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const HOURS = ['12 AM','1 AM','2 AM','3 AM','4 AM','5 AM','6 AM','7 AM','8 AM','9 AM','10 AM','11 AM',
    '12 PM','1 PM','2 PM','3 PM','4 PM','5 PM','6 PM','7 PM','8 PM','9 PM','10 PM','11 PM'];

const SAMPLE_EVENTS = {
    '2026-04-01': [
        { title: 'Sprint Planning', time: '9:00 AM', hour: 9, type: 'primary', meta: 'Engineering' }
    ],
    '2026-04-03': [
        { title: 'Design Review', time: '10:00 AM', hour: 10, type: 'secondary', meta: 'Design' },
        { title: '1:1 with Manager', time: '2:00 PM', hour: 14, type: 'success', meta: 'HR' }
    ],
    '2026-04-07': [
        { title: 'API Integration Demo', time: '11:00 AM', hour: 11, type: 'primary', meta: 'Engineering' }
    ],
    '2026-04-08': [
        { title: 'Team Standup', time: '9:30 AM', hour: 9, type: 'success', meta: 'Engineering' }
    ],
    '2026-04-10': [
        { title: 'Quarterly Review', time: '2:00 PM', hour: 14, type: 'danger', meta: 'Executive' },
        { title: 'Sprint Retro', time: '4:00 PM', hour: 16, type: 'warning', meta: 'Engineering' }
    ],
    '2026-04-14': [
        { title: 'Client Presentation', time: '10:00 AM', hour: 10, type: 'danger', meta: 'Sales' }
    ],
    '2026-04-15': [
        { title: 'UX Workshop', time: '9:00 AM', hour: 9, type: 'secondary', meta: 'Design' },
        { title: 'Database Migration', time: '3:00 PM', hour: 15, type: 'primary', meta: 'Engineering' }
    ],
    '2026-04-17': [
        { title: 'Release v2.1.0', time: '10:00 AM', hour: 10, type: 'success', meta: 'Engineering' }
    ],
    '2026-04-21': [
        { title: 'Board Meeting', time: '1:00 PM', hour: 13, type: 'danger', meta: 'Executive' }
    ],
    '2026-04-22': [
        { title: 'Hackathon Kickoff', time: '9:00 AM', hour: 9, type: 'primary', meta: 'All Teams' }
    ],
    '2026-04-24': [
        { title: 'Performance Reviews', time: '2:00 PM', hour: 14, type: 'warning', meta: 'HR' }
    ],
    '2026-04-28': [
        { title: 'Sprint Planning', time: '9:00 AM', hour: 9, type: 'primary', meta: 'Engineering' },
        { title: 'Marketing Sync', time: '11:00 AM', hour: 11, type: 'secondary', meta: 'Marketing' }
    ],
    '2026-04-30': [
        { title: 'Month-End Close', time: '3:00 PM', hour: 15, type: 'warning', meta: 'Finance' }
    ]
};

let currentMonth = new Date().getMonth();
let currentYear = new Date().getFullYear();
let selectedDate = null;
let currentView = 'month';
let currentWeekStart = getWeekStart(new Date());
let currentDay = new Date();

function getWeekStart(date) {
    const d = new Date(date);
    const day = d.getDay();
    d.setDate(d.getDate() - day);
    d.setHours(0, 0, 0, 0);
    return d;
}

function initCalendar() {
    document.getElementById('calPrev').addEventListener('click', navigatePrev);
    document.getElementById('calNext').addEventListener('click', navigateNext);
    document.getElementById('calToday').addEventListener('click', goToToday);
    renderCurrentView();
}

function navigatePrev() {
    if (currentView === 'month') {
        currentMonth--;
        if (currentMonth < 0) { currentMonth = 11; currentYear--; }
    } else if (currentView === 'week') {
        currentWeekStart.setDate(currentWeekStart.getDate() - 7);
    } else {
        currentDay.setDate(currentDay.getDate() - 1);
    }
    renderCurrentView();
}

function navigateNext() {
    if (currentView === 'month') {
        currentMonth++;
        if (currentMonth > 11) { currentMonth = 0; currentYear++; }
    } else if (currentView === 'week') {
        currentWeekStart.setDate(currentWeekStart.getDate() + 7);
    } else {
        currentDay.setDate(currentDay.getDate() + 1);
    }
    renderCurrentView();
}

function goToToday() {
    const today = new Date();
    currentMonth = today.getMonth();
    currentYear = today.getFullYear();
    currentWeekStart = getWeekStart(today);
    currentDay = new Date(today);
    selectedDate = formatDate(today);
    renderCurrentView();
    renderMiniCalendar();
}

function renderCurrentView() {
    if (currentView === 'month') renderMonthView();
    else if (currentView === 'week') renderWeekView();
    else renderDayView();
    updateUpcoming();
}

function formatDate(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

// ===================== MONTH VIEW =====================
function renderMonthView() {
    const monthLabel = document.getElementById('calMonthLabel');
    const mainArea = document.querySelector('.calendar-main');
    monthLabel.textContent = `${MONTH_NAMES[currentMonth]} ${currentYear}`;

    let html = `<div class="calendar-grid-wrapper">
        <div class="calendar-week-header">
            ${DAY_ABBR.map(d => `<div class="day-label">${d}</div>`).join('')}
        </div>
        <div class="calendar-body" id="calendarBody">`;

    const today = new Date();
    const firstDay = new Date(currentYear, currentMonth, 1).getDay();
    const daysInMonth = new Date(currentYear, currentMonth + 1, 0).getDate();
    const prevDays = new Date(currentYear, currentMonth, 0).getDate();

    for (let x = firstDay; x > 0; x--) {
        html += `<div class="calendar-day other-month"><div class="day-number">${prevDays - x + 1}</div></div>`;
    }

    for (let i = 1; i <= daysInMonth; i++) {
        const dateStr = `${currentYear}-${String(currentMonth + 1).padStart(2, '0')}-${String(i).padStart(2, '0')}`;
        const isToday = i === today.getDate() && currentMonth === today.getMonth() && currentYear === today.getFullYear();
        const isSelected = dateStr === selectedDate;
        const events = SAMPLE_EVENTS[dateStr] || [];

        let classes = 'calendar-day';
        if (isToday) classes += ' today';
        if (isSelected) classes += ' selected';

        let eventsHtml = '';
        if (events.length > 0) {
            eventsHtml = '<div class="calendar-events">';
            events.slice(0, 2).forEach(evt => {
                eventsHtml += `<div class="calendar-event event-${evt.type}">${evt.title}</div>`;
            });
            if (events.length > 2) eventsHtml += `<div class="calendar-event-more">+${events.length - 2} more</div>`;
            eventsHtml += '</div>';
        }

        html += `<div class="${classes}" data-date="${dateStr}"><div class="day-number">${i}</div>${eventsHtml}</div>`;
    }

    const totalCells = firstDay + daysInMonth;
    const remaining = (Math.ceil(totalCells / 7) * 7) - totalCells;
    for (let j = 1; j <= remaining; j++) {
        html += `<div class="calendar-day other-month"><div class="day-number">${j}</div></div>`;
    }

    html += '</div></div>';
    mainArea.innerHTML = html;

    mainArea.querySelectorAll('.calendar-day[data-date]').forEach(el => {
        el.addEventListener('click', () => {
            selectedDate = el.dataset.date;
            renderMonthView();
            renderMiniCalendar();
        });
    });
}

// ===================== WEEK VIEW =====================
function renderWeekView() {
    const monthLabel = document.getElementById('calMonthLabel');
    const mainArea = document.querySelector('.calendar-main');
    const today = new Date();
    const weekDates = [];

    for (let i = 0; i < 7; i++) {
        const d = new Date(currentWeekStart);
        d.setDate(d.getDate() + i);
        weekDates.push(d);
    }

    const weekEnd = new Date(weekDates[6]);
    monthLabel.textContent = `${MONTH_NAMES[weekDates[0].getMonth()]} ${weekDates[0].getDate()} - ${MONTH_NAMES[weekEnd.getMonth()].substring(0, 3)} ${weekEnd.getDate()}, ${weekEnd.getFullYear()}`;

    let html = '<div class="week-view">';

    // Header row: time label + 7 day columns
    html += '<div class="week-day-header" style="background:var(--background);border-bottom:1px solid var(--border);border-right:1px solid var(--border);font-size:0.7rem;color:var(--text-muted);"></div>';
    weekDates.forEach(d => {
        const isToday = d.toDateString() === today.toDateString();
        html += `<div class="week-day-header ${isToday ? 'week-today' : ''}">
            <span>${DAY_ABBR[d.getDay()]}</span>
            <span class="week-day-num">${d.getDate()}</span>
        </div>`;
    });

    // Time slots: 8 AM to 6 PM
    for (let h = 8; h <= 18; h++) {
        const hourIdx = h % 12 === 0 ? 12 : h % 12;
        const ampm = h < 12 ? 'AM' : 'PM';
        const isCurrentHour = h === today.getHours() && weekDates.some(d => d.toDateString() === today.toDateString());

        html += `<div class="week-header-time">${hourIdx} ${ampm}</div>`;

        weekDates.forEach(d => {
            const dateStr = formatDate(d);
            const events = (SAMPLE_EVENTS[dateStr] || []).filter(e => e.hour === h);
            let slotHtml = '';
            events.forEach(evt => {
                slotHtml += `<div class="slot-event event-${evt.type}">${evt.title}</div>`;
            });

            html += `<div class="week-time-slot ${isCurrentHour ? 'week-current-hour' : ''}" data-date="${dateStr}" data-hour="${h}">${slotHtml}</div>`;
        });
    }

    html += '</div>';
    mainArea.innerHTML = html;
}

// ===================== DAY VIEW =====================
function renderDayView() {
    const monthLabel = document.getElementById('calMonthLabel');
    const mainArea = document.querySelector('.calendar-main');
    const today = new Date();
    const dateStr = formatDate(currentDay);

    monthLabel.textContent = `${DAY_NAMES[currentDay.getDay()]}, ${MONTH_NAMES[currentDay.getMonth()]} ${currentDay.getDate()}, ${currentDay.getFullYear()}`;

    const isToday = currentDay.toDateString() === today.toDateString();
    const events = SAMPLE_EVENTS[dateStr] || [];

    let html = '<div class="day-view">';

    // Header
    html += `<div class="day-view-header">
        <div>
            <div class="day-view-date">${MONTH_NAMES[currentDay.getMonth()]} ${currentDay.getDate()}</div>
            <div class="day-view-weekday">${DAY_NAMES[currentDay.getDay()]}</div>
        </div>
        ${isToday ? '<span class="badge badge-success" style="margin-left:auto;">Today</span>' : ''}
    </div>`;

    // Time slots
    html += '<div class="day-view-body">';
    for (let h = 7; h <= 19; h++) {
        const hourIdx = h % 12 === 0 ? 12 : h % 12;
        const ampm = h < 12 ? 'AM' : 'PM';
        const isCurrentHour = isToday && h === today.getHours();
        const hourEvents = events.filter(e => e.hour === h);

        html += `<div class="day-time-label">${hourIdx} ${ampm}</div>`;
        html += `<div class="day-slot ${isCurrentHour ? 'day-current-hour' : ''}">`;
        hourEvents.forEach(evt => {
            html += `<div class="slot-event event-${evt.type}">${evt.title} &middot; ${evt.time}</div>`;
        });
        html += '</div>';
    }
    html += '</div>';

    if (events.length === 0) {
        html += '<div class="day-no-events"><i class="ph ph-calendar-x"></i>No events scheduled for this day</div>';
    }

    html += '</div>';
    mainArea.innerHTML = html;
}

function initMiniCalendar() {
    document.getElementById('miniCalPrev').addEventListener('click', () => {
        currentMonth--;
        if (currentMonth < 0) { currentMonth = 11; currentYear--; }
        renderCurrentView();
        renderMiniCalendar();
    });
    document.getElementById('miniCalNext').addEventListener('click', () => {
        currentMonth++;
        if (currentMonth > 11) { currentMonth = 0; currentYear++; }
        renderCurrentView();
        renderMiniCalendar();
    });
    renderMiniCalendar();
}

function renderMiniCalendar() {
    const grid = document.getElementById('miniCalGrid');
    const label = document.getElementById('miniCalLabel');
    if (!grid || !label) return;

    label.textContent = `${MONTH_NAMES[currentMonth].substring(0, 3)} ${currentYear}`;
    grid.innerHTML = '';

    const today = new Date();
    const firstDay = new Date(currentYear, currentMonth, 1).getDay();
    const daysInMonth = new Date(currentYear, currentMonth + 1, 0).getDate();
    const prevDays = new Date(currentYear, currentMonth, 0).getDate();

    DAY_ABBR.forEach(d => {
        const el = document.createElement('div');
        el.className = 'mini-day-header';
        el.textContent = d.charAt(0);
        grid.appendChild(el);
    });

    for (let x = firstDay; x > 0; x--) {
        const el = document.createElement('div');
        el.className = 'mini-day mini-other';
        el.textContent = prevDays - x + 1;
        grid.appendChild(el);
    }

    for (let i = 1; i <= daysInMonth; i++) {
        const el = document.createElement('div');
        el.className = 'mini-day';
        el.textContent = i;
        const isToday = i === today.getDate() && currentMonth === today.getMonth() && currentYear === today.getFullYear();
        if (isToday) el.classList.add('mini-today');

        const ds = `${currentYear}-${String(currentMonth + 1).padStart(2, '0')}-${String(i).padStart(2, '0')}`;
        if (ds === selectedDate) el.classList.add('mini-selected');

        el.addEventListener('click', () => {
            selectedDate = ds;
            currentDay = new Date(currentYear, currentMonth, i);
            currentWeekStart = getWeekStart(currentDay);
            renderCurrentView();
            renderMiniCalendar();
        });

        grid.appendChild(el);
    }

    const totalCells = firstDay + daysInMonth;
    const remaining = (Math.ceil(totalCells / 7) * 7) - totalCells;
    for (let j = 1; j <= remaining; j++) {
        const el = document.createElement('div');
        el.className = 'mini-day mini-other';
        el.textContent = j;
        grid.appendChild(el);
    }
}

function updateUpcoming() {
    const container = document.getElementById('upcomingList');
    if (!container) return;

    container.innerHTML = '';
    const today = new Date();
    const upcoming = [];

    for (let d = 0; d < 14; d++) {
        const date = new Date(today);
        date.setDate(date.getDate() + d);
        const dateStr = formatDate(date);
        const events = SAMPLE_EVENTS[dateStr] || [];
        events.forEach(evt => upcoming.push({ ...evt, date, dateStr }));
    }

    if (upcoming.length === 0) {
        container.innerHTML = '<div class="text-muted text-sm" style="text-align:center; padding: 1rem;">No upcoming events</div>';
        return;
    }

    upcoming.slice(0, 6).forEach(evt => {
        const item = document.createElement('div');
        item.className = 'upcoming-item';
        const dayName = evt.date.toLocaleDateString('en-US', { weekday: 'short' });
        const monthDay = evt.date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        item.innerHTML = `
            <div class="upcoming-dot dot-${evt.type}"></div>
            <div class="upcoming-info">
                <div class="upcoming-title">${evt.title}</div>
                <div class="upcoming-time"><i class="ph ph-clock"></i> ${evt.time}</div>
                <div class="upcoming-meta">${dayName}, ${monthDay} &middot; ${evt.meta}</div>
            </div>
        `;
        container.appendChild(item);
    });
}

function initViewToggle() {
    const buttons = document.querySelectorAll('.calendar-view-btn');
    buttons.forEach(btn => {
        btn.addEventListener('click', () => {
            buttons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentView = btn.dataset.view;
            renderCurrentView();
        });
    });
}

function initUpcomingClicks() {
    // Placeholder for event detail navigation
}