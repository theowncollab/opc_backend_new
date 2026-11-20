"""Instagram / Facebook verification by DM code (12 hours) and Instagram invite links (7 days)."""
from datetime import timedelta

from database import schema
from utils.helpers_ import col, iso, now


def _request(client, h, platform='instagram', handle='@Priya.Creates'):
    return client.post('/api/users/me/socials/request-code?role=creator', json={'platform': platform, 'handle': handle}, headers=h)


def _req_id(db, pid, platform='instagram'):
    return str(db['ADMIN']['VERIFICATION'].find_one({'personId': pid, 'platform': platform})['_id'])


# ── DM codes ────────────────────────────────────────────────────────────
def test_request_code_normalises_handle_and_queues_for_team(client, make_account, auth, staff, db):
    pid = make_account('priya@email.com', 'creator', profile={'legalName': 'Priya Sharma'})
    r = _request(client, auth(pid), handle='https://www.instagram.com/Priya.Creates/')
    assert r.status_code == 200
    assert r.json()['socials'] == [{'platform': 'instagram', 'handle': '@priya.creates', 'followers': 0, 'verified': False, 'pending': True, 'codeStatus': 'requested'}]
    queue = client.get('/api/admin/verification', headers=staff('Operations')).json()
    assert queue[0]['method'] == 'dm-code' and queue[0]['codeStatus'] == 'requested' and queue[0]['handle'] == '@priya.creates'


def test_bad_handles_and_moj_are_refused(client, make_account, auth):
    h = auth(make_account('a@email.com', 'creator'))
    assert _request(client, h, handle='not a handle!').status_code == 422
    assert _request(client, h, platform='moj', handle='@x').status_code == 422
    assert client.post('/api/users/me/socials/manual-check?role=creator', json={'platform': 'moj', 'handle': '@x'}, headers=h).status_code == 404


def test_full_code_flow(client, make_account, auth, staff, db):
    pid = make_account('priya@email.com', 'creator', profile={'legalName': 'Priya Sharma'})
    h = auth(pid)
    _request(client, h)
    # Before the team sends a code
    assert client.post('/api/users/me/socials/confirm-code?role=creator', json={'platform': 'instagram', 'code': '123456'}, headers=h).status_code == 409

    gen = client.post(f'/api/admin/verification/{_req_id(db, pid)}/code', json={'followers': 45000}, headers=staff('Operations')).json()
    assert len(gen['code']) == 6 and gen['code'] in gen['message'] and gen['handle'] == '@priya.creates'
    hours = (col(schema.VERIFICATION).find_one({'personId': pid})['codeExpiresAt'])
    assert hours > iso(now() + timedelta(hours=11, minutes=59)) and hours <= iso(now() + timedelta(hours=12, minutes=1))
    assert 'code_hash' in col(schema.VERIFICATION).find_one({'personId': pid}) and gen['code'] not in str(col(schema.VERIFICATION).find_one({'personId': pid}))

    me = client.get('/api/users/me?role=creator', headers=h).json()
    assert me['socials'][0]['codeStatus'] == 'sent'

    wrong = '000000' if gen['code'] != '000000' else '111111'
    bad = client.post('/api/users/me/socials/confirm-code?role=creator', json={'platform': 'instagram', 'code': wrong}, headers=h)
    assert bad.status_code == 400 and '4 tries left' in bad.json()['detail']

    good = client.post('/api/users/me/socials/confirm-code?role=creator', json={'platform': 'instagram', 'code': gen['code']}, headers=h)
    assert good.status_code == 200
    s = good.json()['socials'][0]
    assert s['verified'] is True and s['followers'] == 45000 and s['via'] == 'dm-code' and 'pending' not in s
    assert db['ADMIN']['VERIFICATION'].count_documents({'personId': pid}) == 0
    actions = [a['action'] for a in db['ADMIN']['AUDIT'].find()]
    assert 'Generated verification code' in actions and 'Verified account by DM code' in actions


def test_code_expires_after_12_hours_and_limits_tries(client, make_account, auth, staff, db):
    pid = make_account('f@email.com', 'creator')
    h = auth(pid)
    _request(client, h, platform='facebook', handle='facebook.com/priya.creates')
    gen = client.post(f"/api/admin/verification/{_req_id(db, pid, 'facebook')}/code", json={}, headers=staff()).json()

    db['ADMIN']['VERIFICATION'].update_one({'personId': pid}, {'$set': {'codeExpiresAt': iso(now() - timedelta(minutes=1))}})
    expired = client.post('/api/users/me/socials/confirm-code?role=creator', json={'platform': 'facebook', 'code': gen['code']}, headers=h)
    assert expired.status_code == 410
    assert client.get('/api/admin/verification', headers=staff('Operations', 'ops2@theowncollab.com')).json()[0]['codeStatus'] == 'expired'

    # A new code resets the clock and the tries
    gen2 = client.post(f"/api/admin/verification/{_req_id(db, pid, 'facebook')}/code", json={}, headers=staff('Owner', 'own2@theowncollab.com')).json()
    wrong = '000000' if gen2['code'] != '000000' else '111111'
    for _ in range(5):
        client.post('/api/users/me/socials/confirm-code?role=creator', json={'platform': 'facebook', 'code': wrong}, headers=h)
    assert client.post('/api/users/me/socials/confirm-code?role=creator', json={'platform': 'facebook', 'code': gen2['code']}, headers=h).status_code == 429


def test_only_verifying_roles_can_generate_codes(client, make_account, auth, staff, db):
    pid = make_account('p@email.com', 'creator')
    _request(client, auth(pid))
    rid = _req_id(db, pid)
    assert client.post(f'/api/admin/verification/{rid}/code', json={}, headers=staff('Support')).status_code == 403
    assert client.post(f'/api/admin/verification/{rid}/code', json={}, headers=auth(pid)).status_code == 403


# ── Invite links ────────────────────────────────────────────────────────
def test_invite_link_verifies_instagram_on_sign_up(client, make_account, auth, staff, db):
    h_team = staff('Operations')
    made = client.post('/api/admin/invites', json={'handle': '@Neha.Styles', 'name': 'Neha', 'followers': 88000}, headers=h_team).json()
    token, invite = made['token'], made['invite']
    assert invite['status'] == 'active' and invite['handle'] == '@neha.styles'
    assert token not in str(db['ADMIN']['INVITES'].find_one())  # only the hash is stored
    days = invite['expiresAt']
    assert days > iso(now() + timedelta(days=6, hours=23)) and days <= iso(now() + timedelta(days=7, minutes=1))

    view = client.get(f'/api/invites/{token}').json()  # public, no sign-in
    assert view == {'handle': '@neha.styles', 'name': 'Neha', 'expiresAt': invite['expiresAt'], 'status': 'active'}

    pid = make_account('neha@email.com', 'creator', profile={'legalName': 'Neha Rao'})
    r = client.post(f'/api/invites/{token}/redeem', headers=auth(pid))
    assert r.status_code == 200
    s = r.json()['socials'][0]
    assert s == {'platform': 'instagram', 'handle': '@neha.styles', 'followers': 88000, 'verified': True, 'verifiedOn': s['verifiedOn'], 'via': 'invite'}

    listed = client.get('/api/admin/invites', headers=h_team).json()[0]
    assert listed['status'] == 'used' and listed['usedBy'] == 'Neha Rao'
    other = make_account('x@email.com', 'creator')
    again = client.post(f'/api/invites/{token}/redeem', headers=auth(other))
    assert again.status_code == 410 and 'already been used' in again.json()['detail']


def test_google_sign_up_with_invite_token_auto_redeems(client, db, staff, monkeypatch):
    import hashlib
    from routes import auth as auth_routes
    monkeypatch.setattr(auth_routes.id_token, 'verify_oauth2_token', lambda t, r, a: {
        'email': 'priya.invited@example.com', 'email_verified': True, 'name': 'Priya Invited',
        'aud': '448793401303-6serf6pei5g4ra81vd4i57nbhevqav6i.apps.googleusercontent.com'
    })
    h_team = staff('Operations')
    made = client.post('/api/admin/invites', json={'handle': '@priya_creates', 'name': 'Priya', 'followers': 50000}, headers=h_team).json()
    token = made['token']

    # Sign up via google-sign-in with invite_token, omitting user_type
    res = client.post('/auth/google-sign-in', json={'google_id_token': 'dummy', 'invite_token': token}).json()
    assert res['status_code'] == 200
    assert res['redirect_url'].endswith('/onboarding/creator')

    acct = db['USERS']['PERM_USERS'].find_one({'email': 'priya.invited@example.com'})
    assert acct is not None
    assert acct['user_type'] == 'Creator'
    assert acct['socials'][0]['handle'] == '@priya_creates'
    assert acct['socials'][0]['verified'] is True
    assert acct['socials'][0]['via'] == 'invite'

    # Check invite marked used
    invite = db['ADMIN']['INVITES'].find_one({'token_hash': hashlib.sha256(f':{token}'.encode()).hexdigest()})
    assert invite['usedAt'] is not None


def test_invite_expiry_revoke_and_rules(client, make_account, auth, staff, db):
    h_team = staff('Owner')
    token = client.post('/api/admin/invites', json={'handle': '@late'}, headers=h_team).json()['token']
    db['ADMIN']['INVITES'].update_one({}, {'$set': {'expiresAt': iso(now() - timedelta(seconds=1))}})
    assert client.get(f'/api/invites/{token}').json()['status'] == 'expired'
    pid = make_account('late@email.com', 'creator')
    assert client.post(f'/api/invites/{token}/redeem', headers=auth(pid)).status_code == 410

    made = client.post('/api/admin/invites', json={'handle': '@cancel.me'}, headers=h_team).json()
    assert client.post(f"/api/admin/invites/{made['invite']['id']}/revoke", json={'reason': 'no'}, headers=h_team).status_code == 422
    revoked = client.post(f"/api/admin/invites/{made['invite']['id']}/revoke", json={'reason': 'Sent to the wrong person'}, headers=h_team).json()
    assert revoked['status'] == 'revoked'
    assert client.post(f"/api/invites/{made['token']}/redeem", headers=auth(pid)).status_code == 410

    assert client.get('/api/invites/not-a-real-token').status_code == 404
    assert client.post('/api/admin/invites', json={'handle': '@x'}, headers=staff('Support')).status_code == 403
    # Brands can't redeem a creator invite
    brand = make_account('b@brand.in', 'brand')
    fresh = client.post('/api/admin/invites', json={'handle': '@fresh'}, headers=h_team).json()['token']
    assert client.post(f'/api/invites/{fresh}/redeem', headers=auth(brand)).status_code == 404


def test_invite_refused_when_handle_verified_elsewhere(client, make_account, auth, staff):
    make_account('first@email.com', 'creator', socials=[{'platform': 'instagram', 'handle': '@taken', 'followers': 5, 'verified': True}])
    token = client.post('/api/admin/invites', json={'handle': '@taken'}, headers=staff()).json()['token']
    pid = make_account('second@email.com', 'creator')
    r = client.post(f'/api/invites/{token}/redeem', headers=auth(pid))
    assert r.status_code == 409 and 'another OPC account' in r.json()['detail']
