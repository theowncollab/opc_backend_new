"""YouTube verification: Google is faked, so these never call the internet."""
import pytest
import requests

from routes import youtube_verify as yt

CLIENT_ID = 'opc-test.apps.googleusercontent.com'
CHANNEL = {
    'id': 'UC123',
    'snippet': {'title': 'Priya Creates', 'customUrl': '@priyacreates'},
    'statistics': {'subscriberCount': '48200', 'hiddenSubscriberCount': False, 'videoCount': '212'},
}


class Res:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body or {}

    def json(self):
        return self._body


@pytest.fixture
def google(monkeypatch):
    """A fake Google. Change .tokeninfo / .channels to try other answers; .calls records what was asked."""
    monkeypatch.setenv('GOOGLE_CLIENT_ID', CLIENT_ID)

    class Fake:
        tokeninfo = Res(200, {'aud': CLIENT_ID, 'azp': CLIENT_ID, 'scope': f'openid {yt.YOUTUBE_SCOPE}', 'expires_in': '3500'})
        channels = Res(200, {'items': [CHANNEL]})
        calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        Fake.calls.append(('GET', url))
        if url == yt.TOKENINFO_URL:
            if isinstance(Fake.tokeninfo, Exception):
                raise Fake.tokeninfo
            return Fake.tokeninfo
        if url == yt.CHANNELS_URL:
            assert headers['Authorization'] == 'Bearer ya29.test-token'
            assert params['mine'] == 'true'
            return Fake.channels
        raise AssertionError(url)

    def fake_post(url, data=None, timeout=None):
        Fake.calls.append(('POST', url))
        return Res(200)

    Fake.calls = []
    monkeypatch.setattr(yt.requests, 'get', fake_get)
    monkeypatch.setattr(yt.requests, 'post', fake_post)
    return Fake


def verify(client, headers, role='creator', token='ya29.test-token'):
    return client.post(f'/api/users/me/socials/youtube?role={role}', json={'access_token': token}, headers=headers)


def test_verifies_the_channel_and_revokes_the_token(client, google, make_account, auth, db):
    cid = make_account('priya@example.com', 'creator')
    r = verify(client, auth(cid))
    assert r.status_code == 200
    [yt_social] = [s for s in r.json()['socials'] if s['platform'] == 'youtube']
    assert yt_social == {'platform': 'youtube', 'handle': '@priyacreates', 'followers': 48200, 'verified': True,
                         'verifiedOn': yt_social['verifiedOn'], 'via': 'google'}
    stored = db['USERS']['PERM_USERS'].find_one()['socials'][0]
    assert stored['channelId'] == 'UC123' and stored['videos'] == 212
    assert ('POST', yt.REVOKE_URL) in google.calls
    # The profile shows it too, and the team's audit log records it.
    me = client.get('/api/users/me?role=creator', headers=auth(cid)).json()
    assert any(s['platform'] == 'youtube' and s['verified'] for s in me['socials'])
    assert db['ADMIN']['AUDIT'].find_one({'action': 'Verified YouTube channel with Google'})


def test_brands_can_verify_too(client, google, make_account, auth):
    bid = make_account('brand@stylekart.in', 'brand')
    assert verify(client, auth(bid), role='brand').status_code == 200


def test_reverify_refreshes_and_keeps_one_entry(client, google, make_account, auth, db):
    cid = make_account('priya@example.com', 'creator')
    verify(client, auth(cid))
    google.channels = Res(200, {'items': [{**CHANNEL, 'statistics': {'subscriberCount': '50000'}}]})
    r = verify(client, auth(cid))
    socials = [s for s in r.json()['socials'] if s['platform'] == 'youtube']
    assert len(socials) == 1 and socials[0]['followers'] == 50000


def test_other_socials_are_left_alone(client, google, make_account, auth):
    cid = make_account('priya@example.com', 'creator', socials=[{'platform': 'instagram', 'handle': '@priya', 'followers': 900, 'verified': True}])
    platforms = sorted(s['platform'] for s in verify(client, auth(cid)).json()['socials'])
    assert platforms == ['instagram', 'youtube']


def test_hidden_subscriber_count_saves_zero(client, google, make_account, auth):
    google.channels = Res(200, {'items': [{**CHANNEL, 'statistics': {'subscriberCount': '0', 'hiddenSubscriberCount': True}}]})
    cid = make_account('priya@example.com', 'creator')
    yt_social = [s for s in verify(client, auth(cid)).json()['socials'] if s['platform'] == 'youtube'][0]
    assert yt_social['followers'] == 0 and yt_social['verified']


def test_no_custom_url_uses_the_channel_name(client, google, make_account, auth):
    google.channels = Res(200, {'items': [{**CHANNEL, 'snippet': {'title': 'Priya Creates'}}]})
    cid = make_account('priya@example.com', 'creator')
    assert [s for s in verify(client, auth(cid)).json()['socials'] if s['platform'] == 'youtube'][0]['handle'] == 'Priya Creates'


def test_token_for_another_app_is_refused(client, google, make_account, auth, db):
    google.tokeninfo = Res(200, {'aud': 'someone-else.apps.googleusercontent.com', 'scope': yt.YOUTUBE_SCOPE})
    cid = make_account('priya@example.com', 'creator')
    r = verify(client, auth(cid))
    assert r.status_code == 400
    assert ('GET', yt.CHANNELS_URL) not in google.calls  # never read the channel
    assert not db['USERS']['PERM_USERS'].find_one().get('socials')


def test_missing_youtube_permission_is_explained(client, google, make_account, auth):
    google.tokeninfo = Res(200, {'aud': CLIENT_ID, 'scope': 'openid email'})
    r = verify(client, auth(make_account('priya@example.com', 'creator')))
    assert r.status_code == 400 and 'YouTube box' in r.json()['detail']


def test_expired_or_fake_token_is_refused(client, google, make_account, auth):
    google.tokeninfo = Res(400, {'error': 'invalid_token'})
    assert verify(client, auth(make_account('priya@example.com', 'creator'))).status_code == 400


def test_account_without_a_channel(client, google, make_account, auth):
    google.channels = Res(200, {'items': []})
    r = verify(client, auth(make_account('priya@example.com', 'creator')))
    assert r.status_code == 422 and 'doesn’t have a YouTube channel' in r.json()['detail']


def test_youtube_quota_used_up(client, google, make_account, auth):
    google.channels = Res(403, {'error': {'errors': [{'reason': 'quotaExceeded'}]}})
    assert verify(client, auth(make_account('priya@example.com', 'creator'))).status_code == 503


def test_google_unreachable(client, google, make_account, auth):
    google.tokeninfo = requests.ConnectionError('down')
    r = verify(client, auth(make_account('priya@example.com', 'creator')))
    assert r.status_code == 502
    assert ('POST', yt.REVOKE_URL) in google.calls  # still tries to cancel the token


def test_channel_already_on_someone_elses_account(client, google, make_account, auth):
    verify(client, auth(make_account('priya@example.com', 'creator')))
    r = verify(client, auth(make_account('someone@example.com', 'creator')))
    assert r.status_code == 409


def test_same_person_can_use_it_on_creator_and_brand(client, google, make_account, auth):
    verify(client, auth(make_account('priya@example.com', 'creator')))
    assert verify(client, auth(make_account('priya@example.com', 'brand')), role='brand').status_code == 200


def test_not_set_up_without_client_id(client, google, make_account, auth, monkeypatch):
    monkeypatch.setenv('GOOGLE_CLIENT_ID', '')
    assert verify(client, auth(make_account('priya@example.com', 'creator'))).status_code == 503


def test_needs_sign_in(client, google):
    assert client.post('/api/users/me/socials/youtube?role=creator', json={'access_token': 'ya29.test-token'}).status_code == 401
