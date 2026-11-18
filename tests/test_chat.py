"""Chat, support tickets and notifications (DASHBOARD_API.md section C)."""
import pytest

from database import schema
from utils.helpers_ import col, notify, open_conversation


@pytest.fixture
def pair(make_account):
    brand_id = make_account('ananya@stylekart.in', 'brand', profile={'company': 'StyleKart Fashion'})
    creator_id = make_account('priya@email.com', 'creator', profile={'legalName': 'Priya Sharma', 'displayName': '@priya_creates'})
    brand = col(schema.USERS).find_one({'email': 'ananya@stylekart.in'})
    creator = col(schema.USERS).find_one({'email': 'priya@email.com'})
    conv_id = open_conversation(brand, creator, 'FashionFest Winter 2026, Instagram Reel', 'OPC-2026-1117-001')
    return {'brand': brand_id, 'creator': creator_id, 'conv': conv_id}


def test_list_and_detail_from_each_side(client, auth, pair):
    r = client.get('/api/chat/conversations?role=creator', headers=auth(pair['creator']))
    assert r.status_code == 200
    [conv] = r.json()
    assert conv['title'] == 'StyleKart Fashion'
    assert conv['subtitle'] == 'FashionFest Winter 2026, Instagram Reel'
    assert conv['unread'] == 0 and conv['messages'] == []

    r = client.get(f"/api/chat/conversations/{pair['conv']}?role=brand", headers=auth(pair['brand']))
    assert r.json()['title'] == 'Priya Sharma'


def test_non_member_gets_404(client, auth, make_account, pair):
    outsider = make_account('kavya@email.com', 'creator')
    r = client.get(f"/api/chat/conversations/{pair['conv']}?role=creator", headers=auth(outsider))
    assert r.status_code == 404
    assert client.get('/api/chat/conversations?role=creator', headers=auth(outsider)).json() == []


def test_send_normal_message_and_read(client, auth, pair):
    r = client.post(f"/api/chat/conversations/{pair['conv']}/send?role=creator",
                    json={'text': 'Script draft is ready for review.'}, headers=auth(pair['creator']))
    assert r.status_code == 200
    body = r.json()
    assert body['messages'][-1]['from'] == 'me'
    assert body['suspended'] is False

    brand_view = client.get(f"/api/chat/conversations/{pair['conv']}?role=brand", headers=auth(pair['brand'])).json()
    assert brand_view['unread'] == 1
    assert brand_view['messages'][-1]['from'] == 'them'

    assert client.post(f"/api/chat/conversations/{pair['conv']}/read?role=brand", headers=auth(pair['brand'])).json() == {'ok': True}
    assert client.get(f"/api/chat/conversations/{pair['conv']}?role=brand", headers=auth(pair['brand'])).json()['unread'] == 0


def test_phone_number_flags_and_suspends(client, auth, pair, db):
    r = client.post(f"/api/chat/conversations/{pair['conv']}/send?role=brand",
                    json={'text': "Let's sort payment directly, my number is +91 98765 43210"}, headers=auth(pair['brand']))
    assert r.status_code == 200
    body = r.json()
    assert body['flagged'] is True and body['suspended'] is True
    assert body['messages'][-2]['flagged'] is True
    assert body['messages'][-1]['from'] == 'system'

    flags = list(db['CHAT']['FLAGS'].find())
    assert len(flags) == 1
    assert flags[0]['reason'] == 'phone' and flags[0]['fromType'] == 'brand' and flags[0]['status'] == 'open'
    assert flags[0]['from'] == 'StyleKart Fashion'
    assert db['USERS']['PERM_USERS'].find_one({'email': 'ananya@stylekart.in'})['flags'] == 1

    r = client.post(f"/api/chat/conversations/{pair['conv']}/send?role=creator",
                    json={'text': 'Hello?'}, headers=auth(pair['creator']))
    assert r.status_code == 423


@pytest.mark.parametrize('text,reason', [
    ('mail me at priya.s@gmail.com', 'email'),
    ('Ping me on WhatsApp instead', 'off-platform'),
    ('Come to flat no 12 tomorrow', 'address'),
    ('You are an idiot', 'abuse'),
])
def test_scanner_reasons(text, reason):
    from routes.chat import scan
    assert scan(text) == reason


def test_scanner_allows_normal_text():
    from routes.chat import scan
    assert scan('Deadline is 22 November, budget ₹20,000 for 2 reels.') is None


def test_message_length_limits(client, auth, pair):
    r = client.post(f"/api/chat/conversations/{pair['conv']}/send?role=creator", json={'text': '   '}, headers=auth(pair['creator']))
    assert r.status_code == 422


def test_tickets_create_list_priority_and_email(client, auth, pair, mails):
    r = client.post('/api/support/tickets?role=creator', headers=auth(pair['creator']),
                    json={'category': 'Payment', 'subject': 'When is my payout?', 'body': 'I delivered the reel last week and want to know.'})
    assert r.status_code == 200
    t = r.json()
    assert t['id'] == 'TKT-001' and t['status'] == 'open'
    assert col(schema.TICKETS).find_one({'code': 'TKT-001'})['priority'] == 'high'
    assert mails and mails[0]['subject'].startswith('[TKT-001]')

    client.post('/api/support/tickets?role=creator', headers=auth(pair['creator']),
                json={'category': 'Scores', 'subject': 'IIS question', 'body': 'How is my IIS score calculated exactly?'})
    assert col(schema.TICKETS).find_one({'code': 'TKT-002'})['priority'] == 'normal'
    listed = client.get('/api/support/tickets?role=creator', headers=auth(pair['creator'])).json()
    assert [x['id'] for x in listed] == ['TKT-002', 'TKT-001'] or {x['id'] for x in listed} == {'TKT-001', 'TKT-002'}
    assert client.get('/api/support/tickets?role=brand', headers=auth(pair['brand'])).json() == []


def test_ticket_validation(client, auth, pair):
    r = client.post('/api/support/tickets?role=creator', headers=auth(pair['creator']),
                    json={'category': 'Payment', 'subject': 'Short', 'body': 'too short'})
    assert r.status_code == 422


def test_waiting_ticket_shows_open(client, auth, pair):
    col(schema.TICKETS).insert_one({'code': 'TKT-090', 'accountId': pair['creator'], 'subject': 'x', 'status': 'waiting', 'opened': '2026-11-10T00:00:00Z'})
    [t] = client.get('/api/support/tickets?role=creator', headers=auth(pair['creator'])).json()
    assert t['status'] == 'open'


def test_notifications_list_and_read(client, auth, pair):
    notify(pair['creator'], 'StyleKart approved your script.')
    notify(pair['creator'], 'New match for you.')
    items = client.get('/api/notifications?role=creator', headers=auth(pair['creator'])).json()
    assert len(items) == 2 and all(not n['read'] for n in items)
    assert client.post('/api/notifications/read?role=creator', headers=auth(pair['creator'])).json() == {'ok': True}
    items = client.get('/api/notifications?role=creator', headers=auth(pair['creator'])).json()
    assert all(n['read'] for n in items)
    assert client.get('/api/notifications?role=brand', headers=auth(pair['brand'])).json() == []


def test_requires_sign_in(client):
    assert client.get('/api/chat/conversations').status_code == 401
