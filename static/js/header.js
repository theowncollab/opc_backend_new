const signInButton = document.querySelector("#sign-in button");
signInButton.addEventListener("click", () => {
    window.location.href = 'sign-in.html';
});

// Mark the page you're on in the header ("/brands" and "/brands.html" both count).
const here = window.location.pathname.replace(/\.html$/, '').replace(/\/$/, '') || '/index';
document.querySelectorAll('#nav-links a').forEach((link) => {
    const target = new URL(link.href).pathname.replace(/\.html$/, '');
    if (target === here) link.setAttribute('aria-current', 'page');
});
