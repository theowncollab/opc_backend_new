// Home page questions. Opening one closes the others; the morph itself is in index.css.
const faqItems = document.querySelectorAll('.faq-item');

function setOpen(item, open) {
    item.querySelector('.faq-answer').classList.toggle('hidden', !open);
    item.querySelector('.question-wrapper i').classList.toggle('rotate', open);
    item.querySelector('.question-wrapper').setAttribute('aria-expanded', String(open));
}

faqItems.forEach((item) => {
    const question = item.querySelector('.question-wrapper');
    question.setAttribute('aria-expanded', 'false');
    question.addEventListener('click', () => {
        const opening = item.querySelector('.faq-answer').classList.contains('hidden');
        faqItems.forEach((other) => setOpen(other, false));
        setOpen(item, opening);
    });
});

// The General / For brands / For creators / For event partners tabs.
const faqSectionLinks = document.querySelectorAll('.faq-links');

faqSectionLinks.forEach((link) => {
    link.setAttribute('aria-pressed', String(link.classList.contains('selected')));
    link.addEventListener('click', () => {
        const id = link.getAttribute('id');
        for (const section of document.querySelectorAll('.faqs')) {
            section.classList.add('hidden');
        }
        document.querySelector(`#${id}-faqs`).classList.remove('hidden');
        for (const other of faqSectionLinks) {
            other.classList.remove('selected');
            other.setAttribute('aria-pressed', 'false');
        }
        link.classList.add('selected');
        link.setAttribute('aria-pressed', 'true');
    });
});
