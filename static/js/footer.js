const footerScheduleBtn = document.querySelector("#footer-schedule-a-meet-btn");
footerScheduleBtn.addEventListener("click", () => {
  window.location.href = "schedule-a-meet.html";
});

// Newsletter: saves the address (POST /api/newsletter). The team sees sign-ups in the
// team console under Website inbox → Newsletter.
const footerNewsletterForm = document.querySelector("#footer-newsletters-form form");
const footerSubscribeBtn = footerNewsletterForm.querySelector("button");

async function subscribeToNewsletter(e) {
  if (e) e.preventDefault();
  const input = document.getElementById("footer-newsletters-email");
  const email = input.value.trim();
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email)) {
    alert("Enter a valid email address to subscribe.");
    input.focus();
    return;
  }
  footerSubscribeBtn.disabled = true;
  try {
    const res = await fetch("/api/newsletter", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, website: document.getElementById("footer-newsletters-website").value || null }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = Array.isArray(data.detail) ? data.detail[0]?.msg : data.detail;
      alert(detail || "We couldn't subscribe you. Try again.");
      return;
    }
    input.value = "";
    alert(data.message || "You're subscribed.");
  } catch (err) {
    alert("We couldn't reach OPC. Check your connection and try again.");
  } finally {
    footerSubscribeBtn.disabled = false;
  }
}

footerSubscribeBtn.addEventListener("click", subscribeToNewsletter);
// Pressing Enter in the email box submits the form: subscribe instead of reloading the page.
footerNewsletterForm.addEventListener("submit", subscribeToNewsletter);

const footerBottom = document.getElementById("footer-bottom");
document.addEventListener("DOMContentLoaded", () => {
  footerBottom.innerHTML = `<p>&copy; ${new Date().getFullYear()} Own Professional Collaboration. <a href="privacy-policy.html">Privacy policy</a> | <a href="terms-and-conditions.html">Terms and conditions</a></p>`
})