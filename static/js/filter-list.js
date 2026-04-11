document.addEventListener('DOMContentLoaded', () => {
    initFilterChips();
    initSelectAll();
    initTableSearch();
    initViewToggle();
});

function initFilterChips() {
    const chips = document.querySelectorAll('.filter-chip');
    chips.forEach(chip => {
        chip.addEventListener('click', () => {
            chips.forEach(c => c.classList.remove('active'));
            chip.classList.add('active');

            const filter = chip.getAttribute('data-filter');
            const rows = document.querySelectorAll('#recordsTable tbody tr');
            let visibleCount = 0;

            rows.forEach(row => {
                const status = row.getAttribute('data-status');
                if (filter === 'all' || status === filter) {
                    row.style.display = '';
                    visibleCount++;
                } else {
                    row.style.display = 'none';
                }
            });

            const countEl = document.getElementById('recordCount');
            if (countEl) countEl.textContent = visibleCount;
        });
    });
}

function initSelectAll() {
    const selectAll = document.getElementById('selectAll');
    if (!selectAll) return;

    selectAll.addEventListener('change', () => {
        const checkboxes = document.querySelectorAll('.row-check');
        checkboxes.forEach(cb => { cb.checked = selectAll.checked; });
    });
}

function initTableSearch() {
    const searchInput = document.getElementById('tableSearch');
    if (!searchInput) return;

    searchInput.addEventListener('input', () => {
        const query = searchInput.value.toLowerCase();
        const rows = document.querySelectorAll('#recordsTable tbody tr');

        rows.forEach(row => {
            const text = row.textContent.toLowerCase();
            row.style.display = text.includes(query) ? '' : 'none';
        });
    });
}

function initViewToggle() {
    const gridBtn = document.getElementById('viewGrid');
    const listBtn = document.getElementById('viewList');

    if (!gridBtn || !listBtn) return;

    listBtn.addEventListener('click', () => {
        listBtn.classList.add('active');
        gridBtn.classList.remove('active');
    });

    gridBtn.addEventListener('click', () => {
        gridBtn.classList.add('active');
        listBtn.classList.remove('active');
    });
}