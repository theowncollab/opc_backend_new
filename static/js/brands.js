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
    window.addEventListener('scroll', () => {
        const scrollY = window.scrollY;
        const offset = scrollY * intensity;
        element.style.transform = `translateY(${offset}px)`;
    });
}

document.addEventListener('DOMContentLoaded', () => {
    const parallaxElement = document.querySelector('#br-hero-right img');
    addParallaxEffect(parallaxElement, 0.15);
});

const brandsScheduleBtn = document.getElementById('brands-schedule-a-meet-btn');
brandsScheduleBtn.addEventListener('click', () => {
    window.location.href = 'schedule-a-meet.html';
});