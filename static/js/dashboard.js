document.addEventListener('DOMContentLoaded', () => {
    const chartBars = document.querySelectorAll('.chart-bar');
    chartBars.forEach(bar => {
        bar.addEventListener('mouseenter', () => {
            bar.style.transform = 'scaleY(1.05)';
            bar.style.transformOrigin = 'bottom';
        });
        bar.addEventListener('mouseleave', () => {
            bar.style.transform = 'scaleY(1)';
        });
    });
});