"""Google sign-in: sign up once, then sign in; bad tokens are refused."""
from routes import auth as auth_routes


def users(db):
    return list(db['USERS']['PERM_USERS'].find())


def test_google_sign_up_and_sign_in(client, db, mails, monkeypatch):
    monkeypatch.setattr(auth_routes.id_token, 'verify_oauth2_token', lambda token, req, aud: {'email': 'arjun@example.com'})
    r = client.post('/auth/google-sign-in', json={'google_id_token': 't', 'user_type': 'Brand'}).json()
    assert r['status_code'] == 200 and r['message'] == 'User signed up and signed in successfully'
    me = client.get('/auth/me', headers={'Authorization': f"Bearer {r['access_token']}"}).json()
    assert me['user']['email'] == 'arjun@example.com'
    r = client.post('/auth/google-sign-in', json={'google_id_token': 't'}).json()
    assert r['status_code'] == 200 and r['message'] == 'User signed in successfully'
    assert len(users(db)) == 1 and [m['to'] for m in mails] == ['arjun@example.com']


def test_google_sign_up_needs_a_user_type(client, db, monkeypatch):
    monkeypatch.setattr(auth_routes.id_token, 'verify_oauth2_token', lambda token, req, aud: {'email': 'new@example.com'})
    r = client.post('/auth/google-sign-in', json={'google_id_token': 't'}).json()
    assert r['status_code'] == 400 and users(db) == []


def test_google_bad_token(client, db, monkeypatch):
    def boom(*a):
        raise ValueError('bad')

    monkeypatch.setattr(auth_routes.id_token, 'verify_oauth2_token', boom)
    r = client.post('/auth/google-sign-in', json={'google_id_token': 't', 'user_type': 'Brand'}).json()
    assert r['status_code'] == 400 and users(db) == []
