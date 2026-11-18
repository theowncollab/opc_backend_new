const swiper = new Swiper('.swiper-container', {
    slidesPerView: 1.15,
    spaceBetween: 16,
    direction: 'horizontal',
    navigation: {
        nextEl: '.scroll-right',
        prevEl: '.scroll-left',
    },
    breakpoints: {
        640: { slidesPerView: 2, spaceBetween: 24 },
        1024: { slidesPerView: 3, spaceBetween: 32 },
    },
});

function addParallaxEffect(element, intensity) {
    const initialTop = element.getBoundingClientRect().top + window.scrollY;
    element.style.transform = (window.scrollY - initialTop) * intensity;

    window.addEventListener('scroll', () => {
        const scrollY = window.scrollY;
        const offset = (scrollY - initialTop) * intensity;
        element.style.transform = `translateY(${offset}px)`;
    });
}

document.addEventListener('DOMContentLoaded', () => {
    const parallaxElement = document.querySelector('#cr-hero-right img');
    addParallaxEffect(parallaxElement, 0.15);
});

const creatorsScheduleBtn = document.getElementById('cr-hero-schedule-a-meet-btn');
creatorsScheduleBtn.addEventListener('click', () => {
    window.location.href = 'schedule-a-meet.html';
});