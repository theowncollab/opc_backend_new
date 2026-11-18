const isOpcown = window.location.hostname.includes("opcown.com");
const isTheOwnCollab = window.location.hostname.includes("theowncollab.com");
const domainAttribute = isOpcown ? "domain=.opcown.com;" : (isTheOwnCollab ? "domain=.theowncollab.com;" : "");
const cookieOptions = `${domainAttribute} path=/; max-age=604800; Secure; SameSite=Lax`;

const OUR_CLIENT_ID = '448793401303-6serf6pei5g4ra81vd4i57nbhevqav6i.apps.googleusercontent.com';

let selectedUserType = null;

// Save the tokens from sign-in, then open the dashboard.
function finishSignIn(path, body) {
    return fetch(path, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(body),
    })
        .then(response => response.json())
        .then(data => {
            if (data.status_code == 200) {
                alert(data.message);
                document.cookie = `accessToken=${data.access_token}; ${cookieOptions}`;
                document.cookie = `refreshToken=${data.refresh_token}; ${cookieOptions}`;
                document.cookie = `tokenType=${data.token_type}; ${cookieOptions}`;
                window.location.href = data.redirect_url || window.DASHBOARD_URL || '/dashboard/';
            }
            else if (data.status_code == 400) {
                alert(data.message);
            }
            else if (data.status_code == 500) {
                alert(data.message);
            }
            else {
                alert('An unexpected error occurred. Please try again later.');
            }
        })
        .catch(() => alert("We couldn't reach OPC. Check your connection and try again."));
}

function handleCredentialResponse(response) {
    finishSignIn('/auth/google-sign-in', {
        google_id_token: response.credential,
        user_type: selectedUserType
    });
}

window.onload = () => {

    const types = document.querySelectorAll('.type');
    const overlay = document.getElementById('google-sign-in-overlay');

    overlay.addEventListener('click', (e) => {
        if (!selectedUserType) {
            e.stopPropagation();
            alert("Please select a User Type before signing in.");
        }
    });

    types.forEach(type => {
        type.addEventListener('click', () => {
            if (type.classList.contains('active')) {
                type.classList.remove('active');
                selectedUserType = null;
                overlay.style.display = 'block';
            } else {
                types.forEach(t => t.classList.remove('active'));
                type.classList.add('active');
                selectedUserType = type.innerText.trim();
                overlay.style.display = 'none';
            }
        });
    });

    renderGoogleButton();

};

// Google's own button, shown as Google draws it. It must stay visible: Google ignores
// clicks on a hidden button (that's what broke the old look-alike button).
// Google allows a width between 200 and 400 pixels.
function renderGoogleButton() {
    const holder = document.getElementById('g_id_signin');
    const unavailable = document.getElementById('google-sign-in-unavailable');
    const showUnavailable = () => { if (unavailable) unavailable.hidden = false; };

    if (!window.google || !google.accounts || !google.accounts.id) {
        showUnavailable();
        return;
    }
    google.accounts.id.initialize({
        client_id: OUR_CLIENT_ID,
        callback: handleCredentialResponse
    });
    const width = Math.max(200, Math.min(400, Math.floor(holder.parentElement.clientWidth)));
    google.accounts.id.renderButton(holder, {
        type: 'standard',
        theme: 'filled_black',
        size: 'large',
        text: 'continue_with',
        shape: 'pill',
        logo_alignment: 'left',
        width: width
    });
    // If nothing has appeared after a few seconds, say so instead of leaving a dead space.
    setTimeout(() => {
        if (!holder.querySelector('iframe')) showUnavailable();
    }, 5000);
}

const signInScheduleMeetBtn = document.getElementById('sign-in-schedule-a-meet-btn');
signInScheduleMeetBtn.addEventListener('click', () => {
    window.location.href = 'schedule-a-meet.html';
});
