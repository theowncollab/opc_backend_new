const footerScheduleBtn = document.querySelector("#footer-schedule-a-meet-btn");
footerScheduleBtn.addEventListener("click", () => {
  window.location.href = "schedule-a-meet.html";
});

const footerSubscribeBtn = document.querySelector("#footer-newsletters-form form button");
footerSubscribeBtn.addEventListener("click", () => {
  alert("You have successfully subscribed to our newsletters");
});

const footerBottom = document.getElementById("footer-bottom");
document.addEventListener("DOMContentLoaded", () => {
  footerBottom.innerHTML = `<p>&copy; ${new Date().getFullYear()} Own Professional Collaboration. <a href="privacy-policy.html">Privacy policy</a> | <a href="terms-and-conditions.html">Terms and conditions</a></p>`
})