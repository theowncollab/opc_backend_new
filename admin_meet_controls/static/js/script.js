const cancelDate = document.getElementById('cancel-date');
cancelDate.addEventListener('change', async () => {
    await getTimings(cancelDate.value, 'cancel-time-slots', '/get-timings');
})

const cancelBtn = document.getElementById('cancel-meet-btn');
cancelBtn.addEventListener('click', async () => {
    const date = document.getElementById('cancel-date').value;
    if (!date) {
        alert('Please select a date');
        return;
    }
    const timeSlots = document.getElementById('cancel-time-slots').value;
    if (!timeSlots) {
        alert('Please select a time slot');
        return;
    }
    const data = {
        name: 'cancel',
        emails: 'ceo@theowncollab.com',
        user_type: 'admin',
        date: date,
        time_slot: timeSlots,
        google_meet_link: '',
        created_at: ''
    }
    if (prompt('Do you really want to cancel this timing? Type "Y" to confirm or "N" to cancel') == 'Y') {
        const response = await sendRequest(data, '/cancel-timings', 'POST', 'application/json');
        alert(response.message);
    }
})

const removeDate = document.getElementById('remove-date');
removeDate.addEventListener('change', async () => {
    await getTimings(removeDate.value, 'remove-time-slots', '/get-meet-timings');
})

const removeBtn = document.getElementById('remove-meet-btn');
removeBtn.addEventListener('click', async () => {
    const date = document.getElementById('remove-date').value;
    if (!date) {
        alert('Please select a date');
        return;
    }
    const timeSlots = document.getElementById('remove-time-slots').value;
    if (!timeSlots) {
        alert('Please select a time slot');
        return;
    }
    const data = {
        date: date,
        time_slot: timeSlots
    }
    if (prompt('Do you really want to remove this timing? Type "Y" to confirm or "N" to cancel') == 'Y') {
        const response = await sendRequest(data, '/remove-timings', 'POST', 'application/json');
        alert(response.message);
    }
})

const addDate = document.getElementById('add-date');
addDate.addEventListener('change', async () => {
    await getTimings(addDate.value, 'add-time-slots', '/get-timings');
})

const addBtn = document.getElementById('add-meet-btn');
addBtn.addEventListener('click', async () => {
    const date = document.getElementById('add-date').value;
    if (!date) {
        alert('Please select a date');
        return;
    }
    const timeSlots = document.getElementById('add-time-slots').value;
    if (!timeSlots) {
        alert('Please select a time slot');
        return;
    }
    const name = document.getElementById('add-name').value;
    if (!name) {
        alert('Please enter a name');
        return;
    }
    const emails = document.getElementById('add-emails').value;
    if (!emails) {
        alert('Please enter emails');
        return;
    }
    const user_type = document.getElementById('add-user-type').value;
    if (!user_type) {
        alert('Please enter user type');
        return;
    }
    const googleMeetLink = document.getElementById('add-google-meet-link').value;
    if (!googleMeetLink) {
        alert('Please enter google meet link');
        return;
    }
    const data = {
        name: name,
        emails: emails,
        user_type: user_type,
        date: date,
        time_slot: timeSlots,
        google_meet_link: googleMeetLink,
        created_at: new Date().toISOString()
    }
    if (prompt('Do you really want to add this timing? Type "Y" to confirm or "N" to cancel') == 'Y') {
        const response = await sendRequest(data, '/add-meeting', 'POST', 'application/json');
        alert(response.message);
    }
})

async function getTimings(date, elementId, route) {
    const response = await sendGetRequest({ "date": date }, route, 'GET', 'application/json');
    const timeSlots = document.getElementById(elementId);
    timeSlots.innerHTML = '';
    response.valid_timings.forEach(timing => {
        const option = document.createElement('option');
        option.value = timing;
        option.textContent = timing;
        timeSlots.appendChild(option);
    })
}

async function sendGetRequest(query, route, method, contentType) {
    const response = fetch(`${route}?date=${query.date}`, {
        method: method,
        headers: {
            'Content-Type': contentType
        },
    })
    return (await response).json();
}

async function sendRequest(data, route, method, contentType) {
    const response = fetch(route, {
        method: method,
        headers: {
            'Content-Type': contentType
        },
        body: JSON.stringify(data)
    })
    return (await response).json();
}

async function sendEmail(to) {
    const subject = "Meeting Details";
    const body = "Please find the meeting details below:\n\n";
    const from = "ceo@theowncollab.com";
    const response = await sendRequest({ "subject": subject, "body": body, "from": from, "to": to }, '/send-email', 'POST', 'application/json');
    alert(response.message);
}