const isOpcown = window.location.hostname.includes("opcown.com");
const isTheOwnCollab = window.location.hostname.includes("theowncollab.com");
const domainAttribute = isOpcown ? "domain=.opcown.com;" : (isTheOwnCollab ? "domain=.theowncollab.com;" : "");
const cookieOptions = `${domainAttribute} path=/; max-age=604800; Secure; SameSite=Lax`;

const OUR_CLIENT_ID = '448793401303-6serf6pei5g4ra81vd4i57nbhevqav6i.apps.googleusercontent.com';

let selectedUserType = null;
let pendingGoogleToken = null;

// Parse a JWT payload on the client without external libraries
function parseJwt(token) {
    try {
        const base64Url = token.split('.')[1];
        const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
        const jsonPayload = decodeURIComponent(
            atob(base64)
                .split('')
                .map(c => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
                .join('')
        );
        return JSON.parse(jsonPayload);
    } catch {
        return null;
    }
}

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

function promptNewUserModal(details) {
    const modal = document.getElementById('new-user-modal');
    const input = document.getElementById('new-user-username');
    const rolePills = document.querySelectorAll('.auth-modal-role-pill');
    let chosenRole = details.preselectedRole || 'Creator';

    if (input) {
        input.value = details.suggestedName || '';
    }

    rolePills.forEach(pill => {
        const r = pill.getAttribute('data-role');
        if (r.toLowerCase() === chosenRole.toLowerCase()) {
            pill.classList.add('active');
            chosenRole = r;
        } else {
            pill.classList.remove('active');
        }
        pill.onclick = (e) => {
            e.preventDefault();
            rolePills.forEach(p => p.classList.remove('active'));
            pill.classList.add('active');
            chosenRole = r;
        };
    });

    if (modal && typeof modal.showModal === 'function') {
        modal.showModal();
        if (input) {
            setTimeout(() => input.focus(), 150);
        }
    } else {
        const fallbackName = prompt("Welcome to OPC! Please enter your username to complete sign-up:", details.suggestedName || "");
        if (fallbackName !== null && fallbackName.trim()) {
            finishSignIn('/auth/google-sign-in', {
                google_id_token: details.googleToken,
                user_type: chosenRole,
                username: fallbackName.trim()
            });
        }
    }
}

function setupNewUserModal() {
    const form = document.getElementById('new-user-form');
    const cancelBtn = document.getElementById('cancel-new-user-modal');
    const modal = document.getElementById('new-user-modal');

    if (form) {
        form.addEventListener('submit', (e) => {
            e.preventDefault();
            const input = document.getElementById('new-user-username');
            const activePill = document.querySelector('.auth-modal-role-pill.active');
            const chosenRole = activePill ? activePill.getAttribute('data-role') : (selectedUserType || 'Creator');
            const username = (input ? input.value.trim() : '') || 'Member';

            if (modal) modal.close();

            if (pendingGoogleToken) {
                finishSignIn('/auth/google-sign-in', {
                    google_id_token: pendingGoogleToken,
                    user_type: chosenRole,
                    username: username
                });
            }
        });
    }

    if (cancelBtn) {
        cancelBtn.addEventListener('click', () => {
            if (modal) modal.close();
            pendingGoogleToken = null;
        });
    }
}

function handleCredentialResponse(response) {
    pendingGoogleToken = response.credential;
    const payload = parseJwt(response.credential);
    const email = payload ? payload.email : null;
    const suggestedName = payload ? (payload.name || (email ? email.split('@')[0] : '')) : '';

    if (!email) {
        finishSignIn('/auth/google-sign-in', {
            google_id_token: response.credential,
            user_type: selectedUserType
        });
        return;
    }

    // Old or new user? Send Google's token, not the email: the backend checks the
    // token and only answers about the signed-in person's own account.
    fetch('/auth/check-user', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ google_id_token: response.credential })
    })
    .then(res => res.json())
    .then(data => {
        if (data.exists || data.is_staff) {
            // Existing account, or the OPC team (e.g. opc.owncollab@gmail.com):
            // sign in straight away, no role to pick. The team lands in the team console.
            finishSignIn('/auth/google-sign-in', {
                google_id_token: response.credential,
                user_type: data.is_staff ? null : (selectedUserType || data.user_type)
            });
        } else {
            // New user: display modal to ask for username and confirm role
            promptNewUserModal({
                googleToken: response.credential,
                email: email,
                suggestedName: suggestedName,
                preselectedRole: selectedUserType
            });
        }
    })
    .catch(() => {
        finishSignIn('/auth/google-sign-in', {
            google_id_token: response.credential,
            user_type: selectedUserType
        });
    });
}

window.onload = () => {

    const types = document.querySelectorAll('.type');

    // No role is needed before Google: people who already have an account and the
    // OPC team sign straight in. A role tile only pre-selects the role a new member
    // confirms in the sign-up window afterwards.
    const overlay = document.getElementById('google-sign-in-overlay');
    if (overlay) overlay.remove();

    types.forEach(type => {
        type.addEventListener('click', () => {
            if (type.classList.contains('active')) {
                type.classList.remove('active');
                selectedUserType = null;
            } else {
                types.forEach(t => t.classList.remove('active'));
                type.classList.add('active');
                selectedUserType = type.innerText.trim();
            }
        });
    });

    setupNewUserModal();
    renderGoogleButton();

};

// Google's own button, shown as Google draws it.
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
    setTimeout(() => {
        if (!holder.querySelector('iframe')) showUnavailable();
    }, 5000);
}

const signInScheduleMeetBtn = document.getElementById('sign-in-schedule-a-meet-btn');
if (signInScheduleMeetBtn) {
    signInScheduleMeetBtn.addEventListener('click', () => {
        window.location.href = 'schedule-a-meet.html';
    });
}
