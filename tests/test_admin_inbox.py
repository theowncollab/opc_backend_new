"""Website inbox (contact messages, registered events, newsletter) and OPC's permanent owner account."""
from bson import ObjectId

EVENT = {'name': 'Mood Indigo 2026', 'start_date': '2026-12-20T10:00', 'end_date': '2026-12-22T22:00', 'organizer': 'IIT Bombay',
         'location': 'Mumbai', 'poc_email': 'events@moodi.in', 'poc_name': 'Rhea', 'poc_phone': 9876543210}


def _audit(db):
    return [e['action'] for e in db['ADMIN']['AUDIT'].find()]


# ── OPC's own account ────────────────────────────────────────────────────
def test_opc_gmail_is_always_an_owner(client, make_account, auth, monkeypatch):
    # Even when STAFF_OWNER_EMAILS lists someone else entirely
    monkeypatch.setenv('STAFF_OWNER_EMAILS', 'ceo@theowncollab.com')
    h = auth(make_account('opc.owncollab@gmail.com', 'brand'))
    me = client.get('/api/admin/me', headers=h).json()
    assert me['role'] == 'Owner' and me['name'] == 'OPC'
    assert client.get('/api/admin/inbox/messages', headers=h).status_code == 200


def test_opc_gmail_is_raised_to_owner_if_added_with_a_smaller_role(client, make_account, auth, db):
    db['ADMIN']['TEAM'].insert_one({'email': 'opc.owncollab@gmail.com', 'name': 'OPC', 'role': 'Support'})
    h = auth(make_account('OPC.Owncollab@gmail.com', 'creator'))
    assert client.get('/api/admin/me', headers=h).json()['role'] == 'Owner'


def test_sign_in_sends_opc_gmail_to_the_team_console(client, monkeypatch):
    from routes import auth as auth_routes
    monkeypatch.setenv('STAFF_OWNER_EMAILS', 'ceo@theowncollab.com')
    monkeypatch.setattr(auth_routes.id_token, 'verify_oauth2_token', lambda t, r, a: {
        'email': 'opc.owncollab@gmail.com', 'email_verified': True,
        'aud': '448793401303-6serf6pei5g4ra81vd4i57nbhevqav6i.apps.googleusercontent.com'})
    r = client.post('/auth/google-sign-in', json={'google_id_token': 't', 'user_type': 'Brand', 'username': 'OPC'}).json()
    assert r['status_code'] == 200 and r['is_staff'] is True and r['redirect_url'].endswith('/admin')


def test_other_people_still_cant_get_in(client, make_account, auth):
    h = auth(make_account('random@gmail.com', 'creator'))
    assert client.get('/api/admin/me', headers=h).status_code == 403
    assert client.get('/api/admin/inbox/messages', headers=h).status_code == 403


# ── Contact messages ─────────────────────────────────────────────────────
def test_contact_form_is_saved_and_answered_from_the_console(client, staff, mails, db):
    r = client.post('/contact-us', json={'name': 'Kabir', 'email': 'kabir@cafe.in', 'subject': 'Creators in Pune',
                                         'message': 'Can you find <b>food</b> creators?'}).json()
    assert r['status_code'] == 200
    assert mails[-1]['subject'] == 'Contact Us Message from Kabir'  # the team inbox still gets it

    h = staff('Support')
    [m] = client.get('/api/admin/inbox/messages', headers=h).json()
    assert m['name'] == 'Kabir' and m['status'] == 'new' and m['replies'] == []

    out = client.post(f"/api/admin/inbox/messages/{m['id']}/reply", json={'text': 'Yes!\nLet’s talk.'}, headers=h).json()
    assert out['status'] == 'replied' and out['replies'][0]['text'] == 'Yes!\nLet’s talk.'
    reply = mails[-1]
    assert reply['to'] == 'kabir@cafe.in' and reply['subject'] == 'Re: Creators in Pune'
    assert 'Yes!<br>' in reply['body'] and '&lt;b&gt;food&lt;/b&gt;' in reply['body']  # their text is quoted safely

    assert client.post(f"/api/admin/inbox/messages/{m['id']}/status", json={'status': 'closed'}, headers=h).json()['status'] == 'closed'
    assert _audit(db) == ['Replied to a contact message', 'Closed a contact message']


def test_inbox_needs_the_support_permission(client, staff):
    assert client.get('/api/admin/inbox/messages', headers=staff('Finance')).status_code == 403
    assert client.get('/api/admin/inbox/events', headers=staff('Finance', 'f2@theowncollab.com')).status_code == 403


def test_empty_reply_and_unknown_message(client, staff):
    h = staff('Support')
    client.post('/contact-us', json={'name': 'A', 'email': 'a@b.co', 'subject': 's', 'message': 'm'})
    [m] = client.get('/api/admin/inbox/messages', headers=h).json()
    assert client.post(f"/api/admin/inbox/messages/{m['id']}/reply", json={'text': '   '}, headers=h).status_code == 422
    assert client.post('/api/admin/inbox/messages/nope/reply', json={'text': 'hi'}, headers=h).status_code == 404


# ── Registered events ────────────────────────────────────────────────────
def test_registered_events_show_and_can_be_followed_up(client, staff, mails, db):
    assert client.post('/register-event', json=EVENT).json()['status_code'] == 200
    # An older registration with no receivedAt still shows
    db['EVENTS']['REGISTERED_EVENTS'].insert_one({**EVENT, 'name': 'Old fest', '_id': ObjectId()})

    h = staff('Operations')
    events = client.get('/api/admin/inbox/events', headers=h).json()
    assert {e['name'] for e in events} == {'Mood Indigo 2026', 'Old fest'}
    fest = next(e for e in events if e['name'] == 'Mood Indigo 2026')
    assert fest['status'] == 'new' and fest['contactPhone'] == '9876543210' and fest['receivedAt']

    out = client.post(f"/api/admin/inbox/events/{fest['id']}/status", json={'status': 'contacted', 'note': 'Called Rhea'}, headers=h).json()
    assert out['status'] == 'contacted' and out['note'] == 'Called Rhea' and out['updatedBy']
    assert client.post(f"/api/admin/inbox/events/{fest['id']}/status", json={'status': 'bogus'}, headers=h).status_code == 422


def test_register_event_errors_reply_instead_of_crashing(client, monkeypatch):
    from routes import register_event as re_routes

    def boom(*a, **k):
        raise RuntimeError('db down')

    monkeypatch.setattr(re_routes, 'get', boom)
    r = client.post('/register-event', json=EVENT)
    assert r.status_code == 200 and r.json()['status_code'] == 500


# ── Newsletter ───────────────────────────────────────────────────────────
def test_newsletter_signup_is_saved_once(client, staff, db):
    assert 'subscribed' in client.post('/api/newsletter', json={'email': ' Neha@Example.com '}).json()['message']
    assert 'already' in client.post('/api/newsletter', json={'email': 'neha@example.com'}).json()['message']
    assert db['WEBSITE']['NEWSLETTER'].count_documents({}) == 1
    assert client.post('/api/newsletter', json={'email': 'not-an-email'}).status_code == 422
    # Bots that fill the hidden field are quietly ignored
    client.post('/api/newsletter', json={'email': 'bot@spam.io', 'website': 'http://spam'})
    assert db['WEBSITE']['NEWSLETTER'].count_documents({}) == 1


def test_newsletter_list_export_and_remove(client, staff, db):
    for e in ['a@x.com', 'b@x.com']:
        client.post('/api/newsletter', json={'email': e})
    h = staff('Support')
    subs = client.get('/api/admin/inbox/newsletter', headers=h).json()
    assert {s['email'] for s in subs} == {'a@x.com', 'b@x.com'}

    a = next(s for s in subs if s['email'] == 'a@x.com')
    assert client.post(f"/api/admin/inbox/newsletter/{a['id']}/remove", headers=h).json()['status'] == 'unsubscribed'
    csv = client.get('/api/admin/inbox/newsletter?format=csv', headers=h)
    assert csv.headers['content-type'].startswith('text/csv')
    assert 'b@x.com' in csv.text and 'a@x.com' not in csv.text

    # Signing up again after being removed puts them back on the list
    client.post('/api/newsletter', json={'email': 'a@x.com'})
    assert db['WEBSITE']['NEWSLETTER'].find_one({'email': 'a@x.com'})['status'] == 'subscribed'


# ── The team signs in with no role to pick ──────────────────────────────
def _google_is(monkeypatch, email):
    from routes import auth as auth_routes
    monkeypatch.setattr(auth_routes.id_token, 'verify_oauth2_token', lambda t, r, a: {
        'email': email, 'email_verified': True,
        'aud': '448793401303-6serf6pei5g4ra81vd4i57nbhevqav6i.apps.googleusercontent.com'})


def test_first_team_sign_in_needs_no_role(client, db, mails, staff, monkeypatch):
    _google_is(monkeypatch, 'opc.owncollab@gmail.com')
    chk = client.post('/auth/check-user', json={'google_id_token': 't'}).json()
    assert chk['exists'] is False and chk['is_staff'] is True  # the page signs in straight away

    r = client.post('/auth/google-sign-in', json={'google_id_token': 't'}).json()  # no user_type
    assert r['status_code'] == 200 and r['is_staff'] is True and r['redirect_url'].endswith('/admin')
    [acct] = list(db['USERS']['PERM_USERS'].find({'email': 'opc.owncollab@gmail.com'}))
    assert acct['user_type'] == 'Team'
    assert mails == []  # no member welcome email for the team

    h = {'Authorization': f"Bearer {r['access_token']}"}
    assert client.get('/api/admin/me', headers=h).json()['role'] == 'Owner'
    # A team account isn't one of the platform's people
    people = client.get('/api/admin/people', headers=h).json()
    assert all(p['email'] != 'opc.owncollab@gmail.com' for p in people)


def test_invited_team_member_also_skips_the_role(client, db, monkeypatch):
    db['ADMIN']['TEAM'].insert_one({'email': 'meera@theowncollab.com', 'name': 'Meera', 'role': 'Support'})
    _google_is(monkeypatch, 'meera@theowncollab.com')
    assert client.post('/auth/check-user', json={'google_id_token': 't'}).json()['is_staff'] is True
    r = client.post('/auth/google-sign-in', json={'google_id_token': 't'}).json()
    assert r['status_code'] == 200 and r['redirect_url'].endswith('/admin')


def test_members_still_pick_a_role(client, db, monkeypatch):
    _google_is(monkeypatch, 'newbrand@example.com')
    assert client.post('/auth/check-user', json={'google_id_token': 't'}).json()['is_staff'] is False
    assert client.post('/auth/google-sign-in', json={'google_id_token': 't'}).json()['status_code'] == 400
