"""Google sign-in: sign up once, then sign in; bad tokens are refused; check-user only answers for the signed-in person."""
import asyncio

import pytest

from routes import auth as auth_routes
from utils.emails_template_ import welcome_email

OPC_CLIENT = '448793401303-6serf6pei5g4ra81vd4i57nbhevqav6i.apps.googleusercontent.com'


def users(db):
    return list(db['USERS']['PERM_USERS'].find())


def google_says(monkeypatch, email, **extra):
    """Fake Google: every token is a valid sign-in for `email` on OPC's client, unless `extra` overrides it."""
    claims = {'email': email, 'email_verified': True, 'aud': OPC_CLIENT, **extra}
    claims = {k: v for k, v in claims.items() if v is not None}
    monkeypatch.setattr(auth_routes.id_token, 'verify_oauth2_token', lambda token, req, aud: dict(claims))


def test_google_sign_up_and_sign_in(client, db, mails, monkeypatch):
    google_says(monkeypatch, 'arjun@example.com')
    r = client.post('/auth/google-sign-in', json={'google_id_token': 't', 'user_type': 'Brand'}).json()
    assert r['status_code'] == 200 and r['message'] == 'User signed up and signed in successfully'
    me = client.get('/auth/me', headers={'Authorization': f"Bearer {r['access_token']}"}).json()
    assert me['user']['email'] == 'arjun@example.com'
    r = client.post('/auth/google-sign-in', json={'google_id_token': 't'}).json()
    assert r['status_code'] == 200 and r['message'] == 'User signed in successfully'
    assert len(users(db)) == 1 and [m['to'] for m in mails] == ['arjun@example.com']


def test_google_sign_up_needs_a_user_type(client, db, monkeypatch):
    google_says(monkeypatch, 'new@example.com')
    r = client.post('/auth/google-sign-in', json={'google_id_token': 't'}).json()
    assert r['status_code'] == 400 and users(db) == []


def test_google_bad_token(client, db, monkeypatch):
    def boom(*a):
        raise ValueError('bad')

    monkeypatch.setattr(auth_routes.id_token, 'verify_oauth2_token', boom)
    r = client.post('/auth/google-sign-in', json={'google_id_token': 't', 'user_type': 'Brand'}).json()
    assert r['status_code'] == 400 and users(db) == []


@pytest.mark.parametrize('bad', [
    {'aud': 'someone-elses-app.apps.googleusercontent.com'},  # token made for another app
    {'aud': None},                                            # no audience at all
    {'email_verified': False},                                # Google hasn't verified the address
    {'email_verified': None},
])
def test_tokens_not_meant_for_opc_are_refused(client, db, monkeypatch, bad):
    google_says(monkeypatch, 'victim@example.com', **bad)
    r = client.post('/auth/google-sign-in', json={'google_id_token': 't', 'user_type': 'Creator'}).json()
    assert r['status_code'] == 400 and users(db) == []
    chk = client.post('/auth/check-user', json={'google_id_token': 't'}).json()
    assert chk['status_code'] == 400 and chk['exists'] is False


def test_check_user_and_custom_username(client, db, mails, monkeypatch):
    google_says(monkeypatch, 'priya@example.com', name='Priya Google')

    # New person: no account yet
    chk = client.post('/auth/check-user', json={'google_id_token': 't'}).json()
    assert chk['status_code'] == 200 and chk['exists'] is False

    # Sign up with the username they chose
    r = client.post('/auth/google-sign-in', json={'google_id_token': 't', 'user_type': 'Creator', 'username': 'PriyaVlogs'}).json()
    assert r['status_code'] == 200 and r['is_new_user'] is True
    me = client.get('/auth/me', headers={'Authorization': f"Bearer {r['access_token']}"}).json()
    assert me['user']['name'] == 'PriyaVlogs'

    # Now they exist, and the answer carries their role but no name
    chk2 = client.post('/auth/check-user', json={'google_id_token': 't'}).json()
    assert chk2 == {'status_code': 200, 'exists': True, 'user_type': 'Creator'}


def test_check_user_no_longer_accepts_a_bare_email(client, db, make_account):
    make_account('priya@example.com', 'creator', name='Priya')
    r = client.post('/auth/check-user', json={'email': 'priya@example.com'})
    assert r.status_code == 422  # a Google token is required
    assert 'Priya' not in r.text


def test_username_is_cleaned_and_capped(client, db, mails, monkeypatch):
    google_says(monkeypatch, 'neha@example.com')
    messy = '  Neha\u0000\u0007   Styles  ' + 'x' * 80
    r = client.post('/auth/google-sign-in', json={'google_id_token': 't', 'user_type': 'Creator', 'username': messy}).json()
    assert r['status_code'] == 200
    [u] = users(db)
    assert u['name'].startswith('Neha Styles x') and len(u['name']) <= auth_routes.USERNAME_MAX
    assert '\u0000' not in u['name']


def test_blank_username_falls_back_to_google_name(client, db, mails, monkeypatch):
    google_says(monkeypatch, 'rohan@example.com', name='Rohan Mehta')
    client.post('/auth/google-sign-in', json={'google_id_token': 't', 'user_type': 'Brand', 'username': '   '})
    assert users(db)[0]['name'] == 'Rohan Mehta'


def test_welcome_email_escapes_the_name():
    mail = asyncio.run(welcome_email('<b>Evil</b><script>x()</script>', 'creator'))
    assert '<script>' not in mail['body_'] and '&lt;script&gt;' in mail['body_']
    assert 'Creator' in mail['body_']
