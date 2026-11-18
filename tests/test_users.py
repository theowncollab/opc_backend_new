"""Section A: account, onboarding, signature, profile edits, closing, manual checks, work email."""
import base64
import re

PNG = 'data:image/png;base64,' + base64.b64encode(b'\x89PNG\r\n\x1a\n' + b'0' * 100).decode()


def code_from(mail: dict) -> str:
    return re.search(r'<b>(\d{6})</b>', mail['body']).group(1)


# ── Profile ──────────────────────────────────────────────────────────────
def test_me_needs_sign_in(client):
    assert client.get('/api/users/me?role=creator').status_code == 401


def test_me_creator_and_brand_shapes(client, make_account, auth):
    uid = make_account('priya@email.com', 'creator', profile={'legalName': 'Priya Sharma', 'displayName': '@priya', 'city': 'Mumbai', 'niche': 'Fashion'},
                       socials=[{'platform': 'instagram', 'handle': '@priya', 'followers': 45000, 'verified': True, 'verifiedOn': '2026-11-08'}])
    make_account('priya@email.com', 'brand', profile={'company': 'Priya Co', 'contact': 'Priya'})
    me = client.get('/api/users/me?role=creator', headers=auth(uid)).json()
    assert me['legalName'] == 'Priya Sharma' and me['displayName'] == '@priya'
    assert me['payout'] == {} and me['signatureOnFile'] is False and me['onboarded'] is False
    assert me['socials'][0] == {'platform': 'instagram', 'handle': '@priya', 'followers': 45000, 'verified': True, 'verifiedOn': '2026-11-08'}
    assert set(me['iisFactors']) == {'engagement', 'quality', 'reliability', 'growth'}

    brand = client.get('/api/users/me?role=brand', headers=auth(uid)).json()  # same email, other role
    assert brand['companyName'] == 'Priya Co' and brand['contactName'] == 'Priya' and 'workEmail' in brand


def test_me_missing_role_account_is_404(client, make_account, auth):
    uid = make_account('solo@email.com', 'creator')
    assert client.get('/api/users/me?role=brand', headers=auth(uid)).status_code == 404


def test_suspended_account_is_refused(client, make_account, auth):
    uid = make_account('bad@email.com', 'creator', status='suspended')
    assert client.get('/api/users/me?role=creator', headers=auth(uid)).status_code == 403


# ── OTP and profile edits ───────────────────────────────────────────────
def test_profile_edit_needs_fresh_code(client, make_account, auth, mails):
    uid = make_account('edit@email.com', 'creator', profile={'city': 'Pune'})
    h = auth(uid)
    r = client.put('/api/users/me?role=creator', json={'city': 'Mumbai'}, headers=h)
    assert r.status_code == 403 and 'code' in r.json()['detail']

    assert client.post('/api/users/me/otp', json={}, headers=h).json() == {'sent': True}
    assert mails[-1]['to'] == 'edit@email.com'
    code = code_from(mails[-1])
    wrong = '000000' if code != '000000' else '111111'
    assert client.post('/api/users/me/otp/verify', json={'code': wrong}, headers=h).status_code == 400
    assert client.post('/api/users/me/otp/verify', json={'code': code}, headers=h).json() == {'ok': True}

    r = client.put('/api/users/me?role=creator', json={'city': 'Mumbai', 'company': 'ignored for creators'}, headers=h)
    assert r.status_code == 200 and r.json()['city'] == 'Mumbai'


def test_otp_locks_after_five_wrong_tries(client, make_account, auth, mails):
    h = auth(make_account('lock@email.com', 'creator'))
    client.post('/api/users/me/otp', json={}, headers=h)
    code = code_from(mails[-1])
    wrong = '000000' if code != '000000' else '111111'
    for _ in range(5):
        assert client.post('/api/users/me/otp/verify', json={'code': wrong}, headers=h).status_code == 400
    assert client.post('/api/users/me/otp/verify', json={'code': code}, headers=h).status_code == 429


def test_otp_daily_limit(client, make_account, auth, mails):
    h = auth(make_account('spam@email.com', 'creator'))
    for _ in range(5):
        assert client.post('/api/users/me/otp', json={}, headers=h).status_code == 200
    assert client.post('/api/users/me/otp', json={}, headers=h).status_code == 429


# ── Onboarding ───────────────────────────────────────────────────────────
def test_onboarding_progress_copies_profile_keys(client, make_account, auth, db):
    uid = make_account('new@email.com', 'creator')
    h = auth(uid)
    data = {'legalName': 'Arjun Nair', 'displayName': '@arjun', 'city': 'Kochi', 'niche': 'Food', 'random': 'kept in data only'}
    assert client.put('/api/users/me/onboarding?role=creator', json={'step': 1, 'data': data}, headers=h).json() == {'step': 1}
    ob = client.get('/api/users/me/onboarding?role=creator', headers=h).json()
    assert ob == {'step': 1, 'data': data, 'completed': False}
    profile = db['USERS']['PERM_USERS'].find_one({'email': 'new@email.com'})['profile']
    assert profile['legalName'] == 'Arjun Nair' and 'random' not in profile


def test_signature_rules(client, make_account, auth):
    h = auth(make_account('sig@email.com', 'creator'))
    assert client.post('/api/users/me/signature?role=creator', json={'mode': 'draw', 'dataUrl': PNG, 'consentVersion': 'v1'}, headers=h).json() == {'ok': True}
    assert client.post('/api/users/me/signature?role=creator', json={'mode': 'draw', 'dataUrl': 'data:image/jpeg;base64,AAAA', 'consentVersion': 'v1'}, headers=h).status_code == 422
    big = 'data:image/png;base64,' + base64.b64encode(b'0' * (201 * 1024)).decode()
    assert client.post('/api/users/me/signature?role=creator', json={'mode': 'draw', 'dataUrl': big, 'consentVersion': 'v1'}, headers=h).status_code == 422
    assert client.post('/api/users/me/signature?role=creator', json={'mode': 'type', 'typed': '  ', 'consentVersion': 'v1'}, headers=h).status_code == 422
    assert client.post('/api/users/me/signature?role=creator', json={'mode': 'type', 'typed': 'Priya Sharma', 'consentVersion': 'v1'}, headers=h).status_code == 200


def test_complete_onboarding_creator(client, make_account, auth, db):
    uid = make_account('done@email.com', 'creator', status='pending', verified=False)
    h = auth(uid)
    body = {'agreementVersion': '2026-11-17', 'checks': [True, True, True, True]}

    r = client.post('/api/users/me/onboarding/complete?role=creator', json={**body, 'checks': [True, False]}, headers=h)
    assert r.status_code == 422 and 'Tick' in r.json()['detail']
    r = client.post('/api/users/me/onboarding/complete?role=creator', json=body, headers=h)
    assert r.status_code == 422 and 'full legal name' in r.json()['detail']

    client.put('/api/users/me/onboarding?role=creator', json={'step': 1, 'data': {'legalName': 'A N', 'displayName': '@an', 'city': 'Kochi', 'niche': 'Food'}}, headers=h)
    assert 'signature' in client.post('/api/users/me/onboarding/complete?role=creator', json=body, headers=h).json()['detail']
    client.post('/api/users/me/signature?role=creator', json={'mode': 'type', 'typed': 'A N', 'consentVersion': 'v1'}, headers=h)
    assert 'social' in client.post('/api/users/me/onboarding/complete?role=creator', json=body, headers=h).json()['detail']

    client.post('/api/users/me/socials/request-code?role=creator', json={'platform': 'instagram', 'handle': '@an'}, headers=h)
    assert client.post('/api/users/me/onboarding/complete?role=creator', json=body, headers=h).json() == {'status': 'pending'}

    me = client.get('/api/users/me?role=creator', headers=h).json()
    assert me['onboarded'] is True and me['status'] == 'pending'
    req = db['ADMIN']['VERIFICATION'].find_one({'personId': uid, 'kind': 'account'})
    assert req['type'] == 'creator' and req['name'] == 'A N' and len(req['checks']) == 4


def test_complete_onboarding_brand_needs_work_email(client, make_account, auth, mails, db):
    uid = make_account('ops@stylekart.in', 'brand')
    h = auth(uid)
    client.put('/api/users/me/onboarding?role=brand', json={'step': 0, 'data': {'company': 'StyleKart', 'industry': 'Fashion', 'contact': 'Ananya', 'city': 'Mumbai'}}, headers=h)
    client.post('/api/users/me/signature?role=brand', json={'mode': 'type', 'typed': 'Rohan Kapoor', 'consentVersion': 'v1'}, headers=h)
    body = {'agreementVersion': 'v1', 'checks': [True] * 4}
    assert 'work email' in client.post('/api/users/me/onboarding/complete?role=brand', json=body, headers=h).json()['detail']

    client.post('/api/verification/business-email?role=brand', json={'email': 'ananya@stylekart.in'}, headers=h)
    client.post('/api/verification/confirm-email?role=brand', json={'email': 'ananya@stylekart.in', 'code': code_from(mails[-1])}, headers=h)
    assert client.post('/api/users/me/onboarding/complete?role=brand', json=body, headers=h).json() == {'status': 'pending'}
    assert db['ADMIN']['VERIFICATION'].find_one({'personId': uid})['type'] == 'brand'


# ── Closing ──────────────────────────────────────────────────────────────
def test_deactivate_and_delete(client, make_account, auth, db):
    uid = make_account('bye@email.com', 'creator')
    h = auth(uid)
    assert client.post('/api/users/me/deactivate?role=creator', json={'reason': 'Taking a break'}, headers=h).json() == {'status': 'deactivated'}

    uid2 = make_account('gone@email.com', 'brand')
    h2 = auth(uid2)
    assert client.request('DELETE', '/api/users/me?role=brand', json={'reason': 'Privacy', 'confirm': 'delete'}, headers=h2).status_code == 422
    r = client.request('DELETE', '/api/users/me?role=brand', json={'reason': 'Privacy', 'confirm': 'DELETE MY ACCOUNT'}, headers=h2)
    assert r.json() == {'status': 'deletion-requested'}
    doc = db['USERS']['PERM_USERS'].find_one({'email': 'gone@email.com'})
    assert doc['status'] == 'deactivated' and doc['deletionRequestedAt']


# Instagram / Facebook DM codes and invite links: tests/test_social_verify.py

# ── Work email ───────────────────────────────────────────────────────────
def test_work_email_rules(client, make_account, auth, mails, db):
    uid = make_account('brand@stylekart.in', 'brand')
    h = auth(uid)
    assert client.post('/api/verification/business-email?role=brand', json={'email': 'me@gmail.com'}, headers=h).status_code == 422
    assert client.post('/api/verification/business-email?role=brand', json={'email': 'not-an-email'}, headers=h).status_code == 422
    assert client.post('/api/verification/business-email?role=brand', json={'email': 'Ananya@StyleKart.in'}, headers=h).json() == {'sent': True}
    assert mails[-1]['to'] == 'ananya@stylekart.in'
    code = code_from(mails[-1])
    wrong = '000000' if code != '000000' else '111111'
    assert client.post('/api/verification/confirm-email?role=brand', json={'email': 'ananya@stylekart.in', 'code': wrong}, headers=h).status_code == 400
    assert client.post('/api/verification/confirm-email?role=brand', json={'email': 'ananya@stylekart.in', 'code': code}, headers=h).json() == {'verified': True}
    assert client.get('/api/users/me?role=brand', headers=h).json()['workEmail'] == 'ananya@stylekart.in'


def test_work_email_is_brand_only(client, make_account, auth):
    h = auth(make_account('creator@stylekart.in', 'creator'))
    assert client.post('/api/verification/business-email?role=brand', json={'email': 'a@stylekart.in'}, headers=h).status_code == 404
