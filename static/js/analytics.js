document.addEventListener('DOMContentLoaded', () => {
    initPeriodSelector();
});

function initPeriodSelector() {
    const selectors = document.querySelectorAll('.period-selector');
    selectors.forEach(selector => {
        const btns = selector.querySelectorAll('.period-btn');
        btns.forEach(btn => {
            btn.addEventListener('click', () => {
                btns.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
            });
        });
    });
}