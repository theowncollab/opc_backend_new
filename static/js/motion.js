// Page animations: play them only while they're on screen.
//
// - Anything with data-motion gets the class "in-view" while it's visible.
//   Looping scenes pause when they scroll away, so they don't use the CPU.
// - data-motion="once" plays once, the first time it's seen.
// - Without this script, or with "reduce motion" switched on in the device's
//   settings, every scene simply shows its finished state (see motion.css).
(function () {
    'use strict';
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduce || !('IntersectionObserver' in window)) return;

    document.documentElement.classList.add('motion-ready');

    const io = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
            const el = entry.target;
            if (el.dataset.motion === 'once') {
                if (entry.isIntersecting) {
                    el.classList.add('in-view');
                    io.unobserve(el);
                }
                return;
            }
            el.classList.toggle('in-view', entry.isIntersecting);
        });
    }, { threshold: 0.3 });

    const start = () => document.querySelectorAll('[data-motion]').forEach((el) => io.observe(el));
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();
})();
