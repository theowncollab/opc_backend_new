// "Schedule a meet": books through OPC's own backend (no Google Apps Script).
// - Only tomorrow can be booked, counted in India time (IST), 9:00 am to 11:00 pm IST.
// - The meeting link is NOT sent automatically: the OPC team emails it, then marks it
//   sent in the team console (Meetings).
// Paths are relative, like the site's other forms: the backend that serves these
// pages also answers /api/meetings/* (see backend routes/meetings.py).
import { showBtnPreLoader } from "./pre-loader.js";

const API = "/api/meetings";
const BUTTON_TEXT = "Request the meeting";

const form = document.getElementById("schedule-form");
const timeSelect = document.getElementById("time");
const dayLabel = document.getElementById("meet-day");
const errorBox = document.getElementById("schedule-error");
const submitBtn = document.getElementById("schedule-meet-form-btn");
let bookableDate = null;

document.getElementById("schedule-a-meet-sign-in-btn").addEventListener("click", () => {
    window.location.href = "sign-in.html";
});

function showError(text) {
    errorBox.textContent = text;
    errorBox.hidden = !text;
}

// "2026-11-18" -> "Wednesday, 18 November" (the date is already the IST day).
function dayName(isoDate) {
    return new Intl.DateTimeFormat("en-IN", { weekday: "long", day: "numeric", month: "long", timeZone: "UTC" })
        .format(new Date(`${isoDate}T00:00:00Z`));
}

async function loadSlots() {
    timeSelect.innerHTML = '<option value="" disabled selected>Loading tomorrow\'s times…</option>';
    try {
        const res = await fetch(`${API}/slots`);
        if (!res.ok) throw new Error();
        const data = await res.json();
        bookableDate = data.date;
        dayLabel.textContent = `tomorrow, ${dayName(data.date)}`;
        const free = data.slots.filter((s) => s.available);
        timeSelect.innerHTML = `<option value="" disabled selected>${free.length ? "Pick a time (IST) *" : "No times left for tomorrow"}</option>`;
        for (const s of data.slots) {
            const option = document.createElement("option");
            option.value = s.time;
            option.disabled = !s.available;
            option.textContent = `${s.label} IST${s.available ? "" : " (taken)"}`;
            timeSelect.appendChild(option);
        }
    } catch (e) {
        timeSelect.innerHTML = '<option value="" disabled selected>Couldn\'t load times</option>';
        showError("We couldn't load tomorrow's times. Refresh the page, or email support@theowncollab.com.");
    }
}

function readForm() {
    const value = (id) => document.getElementById(id).value.trim();
    const data = {
        name: value("name"),
        email: value("email"),
        phone: value("phone") || null,
        userType: value("type"),
        company: value("company") || null,
        topic: value("topic"),
        date: bookableDate,
        time: timeSelect.value,
        website: document.getElementById("website").value || null,
    };
    if (data.name.length < 2) return [null, "Enter your name."];
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(data.email)) return [null, "Enter a valid email address. We send the meeting link there."];
    if (data.phone && !/^\+?[\d\s-]{8,16}$/.test(data.phone)) return [null, "Enter a valid phone number, or leave it empty."];
    if (!data.userType) return [null, "Tell us whether you're a creator, a brand or an event partner."];
    if (data.topic.length < 10) return [null, "Tell us in a sentence what you'd like to discuss."];
    if (!data.time) return [null, "Pick a time for tomorrow."];
    return [data, ""];
}

form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const [data, problem] = readForm();
    showError(problem);
    if (!data) return;

    showBtnPreLoader(submitBtn, true, "");
    try {
        const res = await fetch(`${API}/book`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
        });
        const body = await res.json().catch(() => ({}));
        if (!res.ok) {
            const detail = Array.isArray(body.detail) ? body.detail[0]?.msg : body.detail;
            showError(detail || "We couldn't book that time. Try again.");
            // Someone took the slot, or the day moved on: show fresh times.
            if (res.status === 409) await loadSlots();
            return;
        }
        form.hidden = true;
        document.getElementById("schedule-done-when").textContent = `${dayName(body.date)} at ${body.label} IST`;
        document.getElementById("schedule-done-message").textContent =
            `We'll email the meeting link to ${data.email} from ${body.fromEmail} before your meeting. ` +
            "If you don't see it, check your spam folder.";
        document.getElementById("schedule-done").hidden = false;
        document.querySelector("#schedule-the-meet #description").hidden = true;
    } catch (err) {
        showError("We couldn't reach OPC. Check your connection and try again.");
    } finally {
        showBtnPreLoader(submitBtn, false, BUTTON_TEXT);
    }
});

loadSlots();
