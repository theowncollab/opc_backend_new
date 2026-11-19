"""Section B: campaigns, readiness score, matches, reveal, deal steps, disputes, monitor, cron."""
from datetime import datetime, timedelta

import pytest

FULL_BRIEF = {
    'objective': 'Brand awareness', 'name': 'FashionFest Winter', 'age': '18–24', 'gender': 'Women',
    'cities': 'Mumbai, Delhi', 'persona': 'College students', 'budget': '20000', 'payType': 'Paid (cash)',
    'contentType': 'Reels and short videos', 'creators': '2–3', 'niche': 'Fashion and lifestyle',
    'deadline': '2026-12-20', 'kpi': 'Engagement rate', 'kpiValue': '5%', 'platforms': ['instagram'],
}


@pytest.fixture
def people(make_account, auth):
    brand = make_account('ananya@stylekart.in', 'brand', profile={'company': 'StyleKart Fashion'})
    priya = make_account('priya@email.com', 'creator', iis=55, profile={'legalName': 'Priya Sharma', 'displayName': '@priya_creates', 'city': 'Mumbai, Maharashtra', 'niche': 'Fashion & Lifestyle'},
                         socials=[{'platform': 'instagram', 'handle': '@priya_creates', 'followers': 45000, 'verified': True}])
    arjun = make_account('arjun@email.com', 'creator', iis=20, profile={'legalName': 'Arjun Nair', 'displayName': '@arjun', 'city': 'Kochi', 'niche': 'Food'})
    make_account('pending@email.com', 'creator', status='pending', verified=False, profile={'legalName': 'Not Yet', 'niche': 'Fashion'})
    outsider = make_account('other@brand.in', 'brand', profile={'company': 'Other Co'})
    return {'brand': brand, 'priya': priya, 'arjun': arjun, 'outsider': outsider, 'h': auth}


def new_campaign(client, headers, **overrides):
    r = client.post('/api/campaigns?role=brand', json={**FULL_BRIEF, 'status': 'matching', **overrides}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def start_deal(client, people):
    hb = people['h'](people['brand'])
    camp = new_campaign(client, hb)
    deal_id = client.post(f"/api/discover/creators/{people['priya']}/reveal?role=brand", json={'campaignId': camp['id']}, headers=hb).json()['dealId']
    return camp, deal_id


# ── Campaigns ────────────────────────────────────────────────────────────
def test_campaigns_need_brand_account(client, people):
    assert client.post('/api/campaigns?role=brand', json=FULL_BRIEF).status_code == 401
    assert client.post('/api/campaigns?role=brand', json=FULL_BRIEF, headers=people['h'](people['priya'])).status_code == 404


def test_cirs_matches_dashboard_formula(client, people):
    hb = people['h'](people['brand'])
    c = new_campaign(client, hb)
    assert c['cirs'] == 80  # every section full: 10 + 15 + 20 + 15 + 20
    assert c['creators'] == 2 and c['budget'] == 20000 and c['status'] == 'matching'
    draft = client.post('/api/campaigns?role=brand', json={'name': 'Bare', 'objective': 'Sales and conversions', 'budget': '₹5,000'}, headers=hb).json()
    assert draft['cirs'] == 23 and draft['status'] == 'draft' and draft['budget'] == 5000


def test_matching_needs_cirs_40(client, people):
    r = client.post('/api/campaigns?role=brand', json={'name': 'Thin', 'objective': 'Sales and conversions', 'status': 'matching'}, headers=people['h'](people['brand']))
    assert r.status_code == 422 and '40' in r.json()['detail']


def test_update_and_list_campaigns(client, people):
    hb = people['h'](people['brand'])
    c = client.post('/api/campaigns?role=brand', json={'name': 'Draft one'}, headers=hb).json()
    r = client.put(f"/api/campaigns/{c['id']}?role=brand", json={**FULL_BRIEF, 'name': 'Draft one', 'status': 'matching'}, headers=hb)
    assert r.json()['cirs'] == 80 and r.json()['status'] == 'matching'
    assert [x['name'] for x in client.get('/api/campaigns?role=brand', headers=hb).json()] == ['Draft one']
    assert client.put(f"/api/campaigns/{c['id']}?role=brand", json={'name': 'Hijack'}, headers=people['h'](people['outsider'])).status_code == 404
    assert client.put('/api/campaigns/not-an-id?role=brand', json={'name': 'x'}, headers=hb).status_code == 404


def test_running_campaign_is_locked(client, people, db):
    hb = people['h'](people['brand'])
    c = new_campaign(client, hb)
    from bson import ObjectId
    db['DEALS']['CAMPAIGNS'].update_one({'_id': ObjectId(c['id'])}, {'$set': {'status': 'active'}})
    assert client.put(f"/api/campaigns/{c['id']}?role=brand", json={'name': 'Change'}, headers=hb).status_code == 409


# ── Matches and reveal ───────────────────────────────────────────────────
def test_matches_are_anonymous_and_ranked(client, people):
    hb = people['h'](people['brand'])
    c = new_campaign(client, hb)
    matches = client.get(f"/api/campaigns/{c['id']}/matches?role=brand", headers=hb).json()
    assert [m['alias'] for m in matches] == ['Creator A', 'Creator B']  # pending creator excluded
    top = matches[0]
    assert top['id'] == people['priya'] and top['followers'] == 45000 and top['topCity'] == 'Mumbai'
    assert 'revealed' not in top and 'Priya' not in str(top)
    assert top['cifs'] > matches[1]['cifs'] and 0 <= top['cifs'] <= 100
    assert client.get(f"/api/campaigns/{c['id']}/matches?role=brand", headers=people['h'](people['outsider'])).status_code == 404


def test_reveal_creates_deal_conversation_and_window(client, people, db):
    hb = people['h'](people['brand'])
    c = new_campaign(client, hb)
    r = client.post(f"/api/discover/creators/{people['priya']}/reveal?role=brand", json={'campaignId': c['id']}, headers=hb).json()
    assert r['name'] == 'Priya Sharma' and r['handle'] == '@priya_creates' and r['dealId'].startswith('OPC-')

    deal = db['DEALS']['DEALS'].find_one({'code': r['dealId']})
    assert deal['stage'] == 'selected' and deal['budget'] == 10000 and deal['ris'] == 30 and deal['platform'] == 'instagram'
    convo = db['CHAT']['CONVERSATIONS'].find_one({'dealId': r['dealId']})
    assert {m['accountId'] for m in convo['members']} == {people['brand'], people['priya']}
    reveal = db['DEALS']['REVEALS'].find_one({'dealId': r['dealId']})
    since = datetime.fromisoformat(reveal['since'].replace('Z', '+00:00'))
    until = datetime.fromisoformat(reveal['until'].replace('Z', '+00:00'))
    months = (until.year - since.year) * 12 + (until.month - since.month)
    assert months == 6 and timedelta(days=180) <= until - since <= timedelta(days=185)
    assert db['NOTIFY']['NOTIFICATIONS'].find_one({'accountId': people['priya']})

    again = client.post(f"/api/discover/creators/{people['priya']}/reveal?role=brand", json={'campaignId': c['id']}, headers=hb).json()
    assert again['dealId'] == r['dealId'] and db['DEALS']['DEALS'].count_documents({}) == 1

    matches = client.get(f"/api/campaigns/{c['id']}/matches?role=brand", headers=hb).json()
    assert matches[0]['revealed'] == {'name': 'Priya Sharma', 'handle': '@priya_creates'}

    monitor = client.get('/api/monitor/active?role=brand', headers=hb).json()
    assert monitor[0]['name'] == 'Priya Sharma' and monitor[0]['status'] == 'clear'


def test_reveal_refuses_unknown_or_unverified_creator(client, people, db):
    hb = people['h'](people['brand'])
    c = new_campaign(client, hb)
    pending = str(db['USERS']['PERM_USERS'].find_one({'email': 'pending@email.com'})['_id'])
    assert client.post(f'/api/discover/creators/{pending}/reveal?role=brand', json={'campaignId': c['id']}, headers=hb).status_code == 404
    assert client.post('/api/discover/creators/000000000000000000000000/reveal?role=brand', json={'campaignId': c['id']}, headers=hb).status_code == 404


# ── Deal steps ───────────────────────────────────────────────────────────
def test_deal_list_and_detail_for_both_sides(client, people):
    _, deal_id = start_deal(client, people)
    hp, hb = people['h'](people['priya']), people['h'](people['brand'])
    mine = client.get('/api/deals?role=creator', headers=hp).json()
    assert [d['id'] for d in mine] == [deal_id]
    d = mine[0]
    assert d['signedOn'] == '' and d['stage'] == 'selected' and 'graceDay' not in d
    assert client.get(f'/api/deals/{deal_id}?role=brand', headers=hb).json()['id'] == deal_id
    assert client.get(f'/api/deals/{deal_id}?role=brand', headers=people['h'](people['outsider'])).status_code == 404
    assert client.get(f'/api/deals/{deal_id}?role=creator', headers=people['h'](people['arjun'])).status_code == 404
    assert client.get('/api/deals?role=creator').status_code == 401


def test_submit_review_approve(client, people, db):
    _, deal_id = start_deal(client, people)
    hp, hb = people['h'](people['priya']), people['h'](people['brand'])
    assert client.post(f'/api/deals/{deal_id}/approve?role=brand', headers=hb).status_code == 409
    assert client.post(f'/api/deals/{deal_id}/submit-content?role=creator', json={'link': 'http://insecure'}, headers=hp).status_code == 422
    assert client.post(f'/api/deals/{deal_id}/submit-content?role=creator', json={'link': 'https://x'}, headers=hb).status_code == 404  # brand isn't the creator

    d = client.post(f'/api/deals/{deal_id}/submit-content?role=creator', json={'link': 'https://instagram.com/reel/1'}, headers=hp).json()
    assert d['stage'] == 'review' and d['graceDay'] == 1 and d['graceEndsOn']
    assert client.post(f'/api/deals/{deal_id}/submit-content?role=creator', json={'link': 'https://instagram.com/reel/2'}, headers=hp).status_code == 409

    assert client.post(f'/api/deals/{deal_id}/approve?role=brand', headers=hp).status_code == 404  # creator can't approve
    d = client.post(f'/api/deals/{deal_id}/approve?role=brand', headers=hb).json()
    assert d['stage'] == 'verify'
    texts = [n['text'] for n in db['NOTIFY']['NOTIFICATIONS'].find({'accountId': people['priya']})]
    assert any('approved' in t for t in texts)


def test_one_revision_rule(client, people):
    _, deal_id = start_deal(client, people)
    hp, hb = people['h'](people['priya']), people['h'](people['brand'])
    client.post(f'/api/deals/{deal_id}/submit-content?role=creator', json={'link': 'https://instagram.com/reel/1'}, headers=hp)
    d = client.post(f'/api/deals/{deal_id}/request-revision?role=brand', json={'note': 'Show the product earlier.'}, headers=hb).json()
    assert d['stage'] == 'scriptApproved' and 'graceDay' not in d
    client.post(f'/api/deals/{deal_id}/submit-content?role=creator', json={'link': 'https://instagram.com/reel/2'}, headers=hp)
    r = client.post(f'/api/deals/{deal_id}/request-revision?role=brand', json={'note': 'One more change please.'}, headers=hb)
    assert r.status_code == 409 and 'one revision' in r.json()['detail']


def test_dispute(client, people, db):
    _, deal_id = start_deal(client, people)
    hp = people['h'](people['priya'])
    assert client.post(f'/api/deals/{deal_id}/dispute?role=creator', json={'note': 'short'}, headers=hp).status_code == 422
    r = client.post(f'/api/deals/{deal_id}/dispute?role=creator', json={'note': 'The brand changed the brief after signing.'}, headers=hp).json()
    assert r['disputeId'] == 'DSP-001'
    doc = db['DEALS']['DISPUTES'].find_one({'code': 'DSP-001'})
    assert doc['raisedBy'] == 'creator' and doc['status'] == 'open' and doc['held'] == 1500 and doc['dealId'] == deal_id
    assert client.post(f'/api/deals/{deal_id}/dispute?role=creator', json={'note': 'Raising it a second time.'}, headers=hp).status_code == 409
    assert client.post(f'/api/deals/{deal_id}/dispute?role=brand', json={'note': 'Not my deal at all here.'}, headers=people['h'](people['outsider'])).status_code == 404


# ── Cron ─────────────────────────────────────────────────────────────────
def test_cron_auto_approve(client, people, db):
    _, deal_id = start_deal(client, people)
    client.post(f'/api/deals/{deal_id}/submit-content?role=creator', json={'link': 'https://instagram.com/reel/1'}, headers=people['h'](people['priya']))
    assert client.get('/cron/deals/auto-approve').status_code == 401
    assert client.get('/cron/deals/auto-approve', headers={'Authorization': 'Bearer wrong'}).status_code == 401

    ok = {'Authorization': 'Bearer test-cron-secret'}
    assert client.get('/cron/deals/auto-approve', headers=ok).json() == {'approved': 0}  # window still open
    db['DEALS']['DEALS'].update_one({'code': deal_id}, {'$set': {'graceEndsOn': '2020-01-01T00:00:00Z'}})
    assert client.get('/cron/deals/auto-approve', headers=ok).json() == {'approved': 1}
    assert db['DEALS']['DEALS'].find_one({'code': deal_id})['stage'] == 'verify'


# ── Team console: campaigns ──────────────────────────────────────────────
def test_team_sees_every_campaign(client, people, staff):
    new_campaign(client, people['h'](people['brand']))
    new_campaign(client, people['h'](people['outsider']), name='Other launch')
    rows = client.get('/api/admin/campaigns', headers=staff('Support')).json()
    assert {(r['name'], r['brand']) for r in rows} == {('FashionFest Winter', 'StyleKart Fashion'), ('Other launch', 'Other Co')}


def test_pause_blocks_new_deals_and_resume_restores(client, people, staff, db):
    hb = people['h'](people['brand'])
    camp = new_campaign(client, hb)
    h = staff('Operations')
    assert client.post(f"/api/admin/campaigns/{camp['id']}/pause", json={'reason': ''}, headers=h).status_code == 422
    out = client.post(f"/api/admin/campaigns/{camp['id']}/pause", json={'reason': 'Brief breaks the creator rules'}, headers=h).json()
    assert out['status'] == 'paused' and out['teamReason'] == 'Brief breaks the creator rules'

    # The brand sees it, can't reveal creators from it, and was notified
    mine = client.get('/api/campaigns?role=brand', headers=hb).json()[0]
    assert mine['status'] == 'paused' and mine['teamReason'] == 'Brief breaks the creator rules'
    r = client.post(f"/api/discover/creators/{people['priya']}/reveal?role=brand", json={'campaignId': camp['id']}, headers=hb)
    assert r.status_code == 409
    assert any('paused your campaign' in n['text'] for n in db['NOTIFY']['NOTIFICATIONS'].find())

    back = client.post(f"/api/admin/campaigns/{camp['id']}/resume", headers=h).json()
    assert back['status'] == 'matching' and back['teamReason'] == ''
    assert client.post(f"/api/discover/creators/{people['priya']}/reveal?role=brand", json={'campaignId': camp['id']}, headers=hb).status_code == 200


def test_close_and_permissions(client, people, staff):
    camp = new_campaign(client, people['h'](people['brand']))
    assert client.post(f"/api/admin/campaigns/{camp['id']}/close", json={'reason': 'Fake brand'}, headers=staff('Support')).status_code == 403
    h = staff('Owner')
    assert client.post(f"/api/admin/campaigns/{camp['id']}/close", json={'reason': 'Fake brand'}, headers=h).json()['status'] == 'closed'
    assert client.post(f"/api/admin/campaigns/{camp['id']}/resume", headers=h).status_code == 409
    assert client.post(f"/api/admin/campaigns/{camp['id']}/close", json={'reason': 'again'}, headers=h).status_code == 409
    assert client.post('/api/admin/campaigns/nope/pause', json={'reason': 'x'}, headers=h).status_code == 404
