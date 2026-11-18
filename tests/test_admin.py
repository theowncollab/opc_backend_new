"""Team console API (DASHBOARD_API.md section D)."""
from bson import ObjectId


def _audit(db):
    return list(db['ADMIN']['AUDIT'].find())


def _creator(make_account, email='priya@email.com', **kw):
    profile = {'legalName': 'Priya Sharma', 'displayName': '@priya_creates', 'city': 'Mumbai'}
    profile.update(kw.pop('profile', {}))
    return make_account(email, 'creator', profile=profile, **kw)


def _brand(make_account, email='ananya@stylekart.in', **kw):
    profile = {'company': 'StyleKart Fashion Pvt. Ltd.', 'contact': 'Ananya Mehta', 'designation': 'Marketing Manager', 'city': 'Mumbai'}
    return make_account(email, 'brand', profile=profile, **kw)


# ── Access ──────────────────────────────────────────────────────────────
def test_non_staff_gets_403(client, make_account, auth):
    uid = _creator(make_account)
    for path in ['/api/admin/me', '/api/admin/overview', '/api/admin/people', '/api/admin/team', '/api/admin/audit']:
        assert client.get(path, headers=auth(uid)).status_code == 403, path
    assert client.get('/api/admin/me').status_code == 401


def test_me_lists_permissions(client, staff):
    body = client.get('/api/admin/me', headers=staff('Support')).json()
    assert body['role'] == 'Support'
    assert 'support.reply' in body['permissions'] and 'people.suspend' not in body['permissions']


def test_roles_lacking_permission_get_403(client, make_account, staff):
    uid = _creator(make_account)
    assert client.post(f'/api/admin/people/{uid}/suspend', json={'reason': 'Repeated abuse'}, headers=staff('Support')).status_code == 403
    assert client.get('/api/admin/audit', headers=staff('Moderator')).status_code == 403
    assert client.get('/api/admin/payouts', headers=staff('Operations')).status_code == 403
    assert client.post('/api/admin/team/invite', json={'email': 'a@theowncollab.com', 'role': 'Support'}, headers=staff('Finance')).status_code == 403


# ── Overview ────────────────────────────────────────────────────────────
def test_overview_counts(client, make_account, staff, db):
    _creator(make_account)
    _brand(make_account)
    make_account('fest@jlmf.in', 'event_partner')
    db['ADMIN']['VERIFICATION'].insert_one({'personId': 'x', 'name': 'X', 'type': 'brand', 'kind': 'account', 'submitted': '2026-11-10T00:00:00Z', 'checks': []})
    db['DEALS']['DISPUTES'].insert_one({'code': 'DSP-001', 'status': 'open'})
    db['CHAT']['FLAGS'].insert_one({'status': 'open'})
    db['ADMIN']['ALERTS'].insert_one({'status': 'open'})
    db['SUPPORT']['TICKETS'].insert_many([{'status': 'open', 'assignee': None}, {'status': 'open', 'assignee': 'Meera'}, {'status': 'closed'}])
    db['DEALS']['DEALS'].insert_many([{'stage': 'review'}, {'stage': 'paid'}])
    body = client.get('/api/admin/overview', headers=staff()).json()
    assert body['queues'] == {'verification': 1, 'disputes': 1, 'moderation': 2, 'payouts': 0, 'support': 1}
    assert body['totals'] == {'creators': 1, 'brands': 2, 'eventPartners': 1, 'dealsInProgress': 1}  # staff account is a brand
    assert len(body['signupsByWeek']) == 5


# ── People ──────────────────────────────────────────────────────────────
def test_people_list_filters_and_shape(client, make_account, staff, db):
    pid = _creator(make_account, socials=[{'platform': 'instagram', 'handle': '@priya_creates', 'followers': 45000, 'verified': True}], iis=28)
    _brand(make_account, status='pending')
    db['DEALS']['DEALS'].insert_one({'code': 'OPC-1', 'creatorAccountId': pid, 'stage': 'review'})
    h = staff('Support')
    people = client.get('/api/admin/people?type=creator', headers=h).json()
    assert [p['name'] for p in people] == ['Priya Sharma']
    p = people[0]
    assert set(['id', 'name', 'sub', 'type', 'email', 'city', 'status', 'verified', 'joined', 'lastActive', 'deals', 'flags', 'notes']) <= set(p)
    assert p['id'] == pid and p['sub'] == '@priya_creates' and p['deals'] == 1 and p['iis'] == 28
    assert p['socials'] == [{'platform': 'instagram', 'handle': '@priya_creates', 'followers': 45000}]
    assert [x['name'] for x in client.get('/api/admin/people?status=pending', headers=h).json()] == ['StyleKart Fashion Pvt. Ltd.']
    assert len(client.get('/api/admin/people?q=mumbai', headers=h).json()) == 2
    assert client.get('/api/admin/people?q=stylekart', headers=h).json()[0]['sub'] == 'Ananya Mehta, Marketing Manager'


def test_person_detail_includes_deals(client, make_account, staff, db):
    pid = _creator(make_account)
    db['DEALS']['DEALS'].insert_one({'code': 'OPC-2026-1108-001', 'campaignName': 'FashionFest', 'brandName': 'StyleKart', 'creatorName': 'Priya Sharma',
                                     'creatorAccountId': pid, 'budget': 5000, 'ris': 31, 'stage': 'review', 'updatedAt': '2026-11-15T10:00:00Z'})
    body = client.get(f'/api/admin/people/{pid}', headers=staff()).json()
    assert body['deals'] == [{'id': 'OPC-2026-1108-001', 'campaign': 'FashionFest', 'brand': 'StyleKart', 'creator': 'Priya Sharma',
                              'budget': 5000, 'ris': 31, 'stage': 'review', 'escrow': None, 'updated': '2026-11-15T10:00:00Z'}]
    assert client.get(f'/api/admin/people/{ObjectId()}', headers=staff('Finance', 'f2@theowncollab.com')).status_code == 404


def test_suspend_and_reactivate(client, make_account, staff, mails, db):
    pid = _creator(make_account)
    h = staff('Moderator')
    assert client.post(f'/api/admin/people/{pid}/suspend', json={'reason': 'bad'}, headers=h).status_code == 422
    r = client.post(f'/api/admin/people/{pid}/suspend', json={'reason': 'Repeated abusive messages'}, headers=h)
    assert r.status_code == 200 and r.json()['status'] == 'suspended'
    assert mails[-1]['to'] == 'priya@email.com' and 'suspended' in mails[-1]['subject']
    entry = _audit(db)[-1]
    assert entry['actor'] == 'Moderator' and entry['action'] == 'Suspended account' and 'Repeated abusive messages' in entry['target']
    r = client.post(f'/api/admin/people/{pid}/reactivate', json={'reason': 'Appeal accepted by phone'}, headers=h)
    assert r.json()['status'] == 'active'
    assert _audit(db)[-1]['action'] == 'Reactivated account'


def test_notes_email_and_socials(client, make_account, staff, mails, db):
    pid = _creator(make_account)
    h = staff('Operations')
    assert client.post(f'/api/admin/people/{pid}/notes', json={'text': '  '}, headers=h).status_code == 422
    client.post(f'/api/admin/people/{pid}/notes', json={'text': 'First note'}, headers=h)
    body = client.post(f'/api/admin/people/{pid}/notes', json={'text': 'Second note'}, headers=h).json()
    assert [n['text'] for n in body['notes']] == ['Second note', 'First note']
    assert body['notes'][0]['by'] == 'Operations (Operations)'
    assert client.post(f'/api/admin/people/{pid}/email', json={'subject': 'Hi', 'body': ''}, headers=h).status_code == 422
    assert client.post(f'/api/admin/people/{pid}/email', json={'subject': 'Hello', 'body': 'Line 1\nLine 2'}, headers=h).json() == {'sent': True}
    assert mails[-1]['body'] == 'Line 1<br>Line 2'
    db['ADMIN']['VERIFICATION'].insert_one({'personId': pid, 'kind': 'social', 'platform': 'moj', 'name': 'Priya', 'type': 'creator', 'checks': []})
    body = client.patch(f'/api/admin/people/{pid}/socials', json={'platform': 'moj', 'handle': '@priya_moj', 'followers': 21000}, headers=h).json()
    assert body['socials'] == [{'platform': 'moj', 'handle': '@priya_moj', 'followers': 21000}]
    assert db['ADMIN']['VERIFICATION'].count_documents({}) == 0
    assert [e['action'] for e in _audit(db)] == ['Added note', 'Added note', 'Sent email', 'Recorded account check']


# ── Verification ────────────────────────────────────────────────────────
def test_verification_account_approve_reject_info(client, make_account, staff, mails, db):
    a = _brand(make_account, status='pending', verified=False)
    b = _creator(make_account, status='pending', verified=False)
    ra = db['ADMIN']['VERIFICATION'].insert_one({'personId': a, 'name': 'StyleKart', 'type': 'brand', 'kind': 'account', 'submitted': '2026-11-11T00:00:00Z',
                                                 'checks': [{'label': 'Work email confirmed', 'ok': True}]}).inserted_id
    rb = db['ADMIN']['VERIFICATION'].insert_one({'personId': b, 'name': 'Priya', 'type': 'creator', 'kind': 'account', 'submitted': '2026-11-12T00:00:00Z', 'checks': []}).inserted_id
    h = staff('Operations')
    listed = client.get('/api/admin/verification', headers=h).json()
    assert [r['name'] for r in listed] == ['StyleKart', 'Priya'] and listed[0]['checks'][0]['ok'] is True
    assert client.post(f'/api/admin/verification/{ra}/approve', json={'reason': ''}, headers=h).status_code == 422
    assert client.post(f'/api/admin/verification/{ra}/request-info', json={'reason': 'Please send your GST number'}, headers=h).json() == {'ok': True}
    assert 'GST' in mails[-1]['body'] and db['ADMIN']['VERIFICATION'].count_documents({}) == 2
    client.post(f'/api/admin/verification/{ra}/approve', json={'reason': 'Domain checked by phone'}, headers=h)
    acc = db['USERS']['PERM_USERS'].find_one({'_id': ObjectId(a)})
    assert acc['status'] == 'active' and acc['verified'] is True
    client.post(f'/api/admin/verification/{rb}/reject', json={'reason': 'Bought followers'}, headers=h)
    assert db['USERS']['PERM_USERS'].find_one({'_id': ObjectId(b)})['status'] == 'deactivated'
    assert 'Bought followers' in mails[-1]['body']
    assert db['ADMIN']['VERIFICATION'].count_documents({}) == 0
    assert client.post(f'/api/admin/verification/{ra}/approve', json={'reason': 'Again please'}, headers=h).status_code == 404
    assert [e['action'] for e in _audit(db)] == ['Asked for more information', 'Approved verification', 'Rejected verification']


def test_verification_social(client, make_account, staff, db):
    pid = _creator(make_account, socials=[{'platform': 'moj', 'handle': '@p', 'followers': 0, 'verified': False, 'pending': True}])
    r1 = db['ADMIN']['VERIFICATION'].insert_one({'personId': pid, 'name': 'Priya', 'type': 'creator', 'kind': 'social', 'platform': 'moj', 'handle': '@p', 'checks': []}).inserted_id
    h = staff()
    assert client.get('/api/admin/verification', headers=h).json()[0]['platform'] == 'moj'
    client.post(f'/api/admin/verification/{r1}/approve', json={'reason': 'Checked the bio code'}, headers=h)
    s = db['USERS']['PERM_USERS'].find_one({'_id': ObjectId(pid)})['socials'][0]
    assert s['verified'] is True and s['pending'] is False and s['verifiedOn']
    db['USERS']['PERM_USERS'].update_one({'_id': ObjectId(pid)}, {'$push': {'socials': {'platform': 'x', 'handle': '@q', 'pending': True, 'verified': False}}})
    r2 = db['ADMIN']['VERIFICATION'].insert_one({'personId': pid, 'name': 'Priya', 'type': 'creator', 'kind': 'social', 'platform': 'x', 'checks': []}).inserted_id
    client.post(f'/api/admin/verification/{r2}/reject', json={'reason': 'Handle not found'}, headers=h)
    acc = db['USERS']['PERM_USERS'].find_one({'_id': ObjectId(pid)})
    assert [s['platform'] for s in acc['socials']] == ['moj'] and acc['status'] == 'active'


# ── Deals ───────────────────────────────────────────────────────────────
def test_deals_list_and_stage(client, make_account, staff, db):
    b = _brand(make_account)
    c = _creator(make_account)
    db['DEALS']['DEALS'].insert_one({'code': 'OPC-1', 'campaignName': 'C', 'brandName': 'B', 'creatorName': 'P', 'brandAccountId': b, 'creatorAccountId': c,
                                     'budget': 5000, 'ris': 31, 'stage': 'finalised', 'updatedAt': '2026-11-10T00:00:00Z', 'escrow': 'funded'})
    deals = client.get('/api/admin/deals', headers=staff('Support')).json()
    assert deals[0]['id'] == 'OPC-1' and deals[0]['escrow'] is None
    assert client.post('/api/admin/deals/OPC-1/stage', json={'stage': 'signed'}, headers=staff('Support', 's2@theowncollab.com')).status_code == 403
    h = staff('Operations')
    assert client.post('/api/admin/deals/OPC-1/stage', json={'stage': 'nope'}, headers=h).status_code == 422
    r = client.post('/api/admin/deals/OPC-1/stage', json={'stage': 'signed'}, headers=h)
    assert r.json()['stage'] == 'signed'
    doc = db['DEALS']['DEALS'].find_one({'code': 'OPC-1'})
    assert doc['signedOn'] and doc['updatedAt'] != '2026-11-10T00:00:00Z'
    assert db['NOTIFY']['NOTIFICATIONS'].count_documents({}) == 2
    assert _audit(db)[-1]['action'] == 'Moved deal stage'
    assert client.post('/api/admin/deals/NOPE/stage', json={'stage': 'signed'}, headers=h).status_code == 404


# ── Disputes ────────────────────────────────────────────────────────────
def test_disputes_resolve(client, make_account, staff, db):
    b = _brand(make_account)
    c = _creator(make_account)
    db['DEALS']['DEALS'].insert_one({'code': 'OPC-1', 'brandAccountId': b, 'creatorAccountId': c})
    db['DEALS']['DISPUTES'].insert_one({'code': 'DSP-007', 'dealId': 'OPC-1', 'campaign': 'Protein Week', 'brand': 'FitFuel', 'creator': 'Kavya',
                                        'raisedBy': 'brand', 'raisedByAccountId': b, 'reason': 'No #ad', 'held': 1800, 'opened': '2026-11-15T17:30:00Z',
                                        'status': 'open', 'evidence': ['x']})
    h = staff('Finance')
    listed = client.get('/api/admin/disputes', headers=h).json()
    assert listed[0]['id'] == 'DSP-007' and 'outcome' not in listed[0]
    assert client.post('/api/admin/disputes/DSP-007/resolve', json={'outcome': 'split', 'creatorShare': 60, 'note': 'short'}, headers=h).status_code == 422
    assert client.post('/api/admin/disputes/DSP-007/resolve', json={'outcome': 'other', 'creatorShare': 60, 'note': 'long enough note'}, headers=h).status_code == 422
    r = client.post('/api/admin/disputes/DSP-007/resolve', json={'outcome': 'split', 'creatorShare': 60, 'note': 'Disclosure added next morning'}, headers=h)
    assert r.status_code == 200
    assert r.json()['status'] == 'resolved' and r.json()['outcome'] == 'Split: 60% to the creator, 40% to the brand'
    assert db['NOTIFY']['NOTIFICATIONS'].count_documents({}) == 2
    assert client.post('/api/admin/disputes/DSP-007/resolve', json={'outcome': 'refund', 'creatorShare': 0, 'note': 'Changing my mind now'}, headers=h).status_code == 409
    assert 'Disclosure added' in _audit(db)[-1]['target']


def test_payouts_empty_while_payments_off(client, staff):
    assert client.get('/api/admin/payouts', headers=staff('Finance')).json() == []


# ── Moderation ──────────────────────────────────────────────────────────
def _flag(db, sender, conv_id, **kw):
    doc = {'conversationId': conv_id, 'conversation': 'StyleKart ↔ Priya', 'messageId': 'm', 'fromAccountId': sender, 'from': 'StyleKart',
           'fromType': 'brand', 'message': 'WhatsApp me 98XXXXXXXX', 'reason': 'phone', 'at': '2026-11-14T14:10:00Z', 'status': 'open'}
    doc.update(kw)
    return str(db['CHAT']['FLAGS'].insert_one(doc).inserted_id)


def test_flags_dismiss_warn_suspend(client, make_account, staff, mails, db):
    sender = _brand(make_account)
    conv = str(db['CHAT']['CONVERSATIONS'].insert_one({'members': [], 'suspended': True, 'flagged': True}).inserted_id)
    f1, f2, f3 = _flag(db, sender, conv), _flag(db, sender, conv, at='2026-11-15T00:00:00Z'), _flag(db, sender, conv, at='2026-11-16T00:00:00Z')
    assert client.get('/api/admin/moderation/flags', headers=staff('Support')).status_code == 403
    h = staff('Moderator')
    listed = client.get('/api/admin/moderation/flags', headers=h).json()
    assert [x['id'] for x in listed] == [f3, f2, f1]
    assert set(listed[0]) == {'id', 'conversation', 'from', 'fromType', 'message', 'reason', 'at', 'status'}
    assert client.post(f'/api/admin/moderation/flags/{f1}/dismiss', json={}, headers=h).json()['status'] == 'dismissed'
    assert db['CHAT']['CONVERSATIONS'].find_one({'_id': ObjectId(conv)})['suspended'] is False
    assert client.post(f'/api/admin/moderation/flags/{f1}/warn', json={'reason': 'Sharing numbers again'}, headers=h).status_code == 409
    assert client.post(f'/api/admin/moderation/flags/{f2}/warn', json={'reason': 'no'}, headers=h).status_code == 422
    assert client.post(f'/api/admin/moderation/flags/{f2}/warn', json={'reason': 'First warning for contact sharing'}, headers=h).json()['status'] == 'warned'
    assert mails[-1]['to'] == 'ananya@stylekart.in'
    client.post(f'/api/admin/moderation/flags/{f3}/suspend', json={'reason': 'Third time sharing contacts'}, headers=h)
    assert db['USERS']['PERM_USERS'].find_one({'_id': ObjectId(sender)})['status'] == 'suspended'
    assert [e['action'] for e in _audit(db)] == ['Dismissed flag and restored chat', 'Warned sender', 'Suspended account']


def test_alerts_report_and_actions(client, make_account, staff, mails, db):
    _brand(make_account)
    _creator(make_account, email='sneha@email.com', profile={'legalName': 'Sneha Mehra'})
    db['DEALS']['REVEALS'].insert_one({'brandName': 'StyleKart Fashion Pvt. Ltd.', 'creatorName': 'Sneha Mehra', 'until': '2027-05-05T00:00:00Z'})
    h = staff('Moderator')
    assert client.post('/api/admin/alerts', json={'brand': 'StyleKart', 'creator': 'Sneha', 'evidence': 'short'}, headers=h).status_code == 422
    a = client.post('/api/admin/alerts', json={'brand': 'StyleKart Fashion', 'creator': 'Sneha Mehra',
                                                'evidence': 'Instagram post tagging @stylekart, no OPC deal'}, headers=h).json()
    assert a['status'] == 'open' and a['confidence'] == 0.5 and a['windowEnds'] == '2027-05-05T00:00:00Z'
    assert client.post(f"/api/admin/alerts/{a['id']}/investigate", json={'reason': 'Asked both for an explanation'}, headers=h).json()['status'] == 'investigating'
    r = client.post(f"/api/admin/alerts/{a['id']}/penalise", json={'reason': 'Confirmed paid post outside OPC'}, headers=h)
    assert r.json()['status'] == 'penalised'
    statuses = {acc['email']: acc['status'] for acc in db['USERS']['PERM_USERS'].find()}
    assert statuses['ananya@stylekart.in'] == 'suspended' and statuses['sneha@email.com'] == 'suspended'
    assert len([m for m in mails if 'suspended' in m['subject']]) == 2
    assert client.post(f"/api/admin/alerts/{a['id']}/false-positive", json={'reason': 'Changed my mind'}, headers=h).status_code == 409
    b = client.post('/api/admin/alerts', json={'brand': 'X', 'creator': 'Y', 'evidence': 'A tip from a follower', 'confidence': 0.2}, headers=h).json()
    assert client.post(f"/api/admin/alerts/{b['id']}/false-positive", json={'reason': 'Post was organic'}, headers=h).json()['status'] == 'false-positive'
    c = client.post('/api/admin/alerts', json={'brand': 'Z', 'creator': 'W', 'evidence': 'Story mention seen by the team'}, headers=h).json()
    # Open alerts first, then closed ones newest first
    assert [x['id'] for x in client.get('/api/admin/alerts', headers=h).json()][0] == c['id']
    assert {x['id'] for x in client.get('/api/admin/alerts', headers=h).json()} == {a['id'], b['id'], c['id']}
    assert 'Marked alert as false positive' in [e['action'] for e in _audit(db)]


# ── Support tickets ─────────────────────────────────────────────────────
def test_tickets_patch_and_reply(client, make_account, staff, mails, db):
    pid = _creator(make_account)
    db['SUPPORT']['TICKETS'].insert_one({'code': 'TKT-045', 'accountId': pid, 'from': 'Priya Sharma', 'fromType': 'creator', 'subject': 'Payout failed',
                                         'category': 'Payment', 'priority': 'high', 'status': 'open', 'assignee': None, 'opened': '2026-11-17T08:05:00Z'})
    db['ADMIN']['TEAM'].insert_one({'email': 'meera@theowncollab.com', 'name': 'Meera', 'role': 'Support'})
    h = staff('Support')
    listed = client.get('/api/admin/tickets', headers=h).json()
    assert listed[0] == {'id': 'TKT-045', 'from': 'Priya Sharma', 'fromType': 'creator', 'subject': 'Payout failed', 'category': 'Payment',
                         'priority': 'high', 'status': 'open', 'assignee': None, 'opened': '2026-11-17T08:05:00Z'}
    assert client.patch('/api/admin/tickets/TKT-045', json={'assignee': 'Nobody Here'}, headers=h).status_code == 422
    assert client.patch('/api/admin/tickets/TKT-045', json={'assignee': 'Meera'}, headers=h).json()['assignee'] == 'Meera'
    assert client.patch('/api/admin/tickets/TKT-045', json={'assignee': None}, headers=h).json()['assignee'] is None
    assert client.patch('/api/admin/tickets/TKT-045', json={'status': 'bogus'}, headers=h).status_code == 422
    r = client.post('/api/admin/tickets/TKT-045/reply', json={'text': 'We are checking your bank details.'}, headers=h).json()
    assert r['status'] == 'waiting'
    assert mails[-1]['to'] == 'priya@email.com' and 'TKT-045' in mails[-1]['subject']
    assert client.patch('/api/admin/tickets/TKT-045', json={'status': 'closed'}, headers=h).json()['status'] == 'closed'
    assert client.post('/api/admin/tickets/TKT-999/reply', json={'text': 'Hi'}, headers=h).status_code == 404


# ── Team ────────────────────────────────────────────────────────────────
def test_team_rules(client, make_account, auth, staff, mails, db):
    owner_account = make_account('owner@theowncollab.com', 'brand')  # bootstrap owner via STAFF_OWNER_EMAILS
    h = auth(owner_account)
    assert client.get('/api/admin/me', headers=h).json()['role'] == 'Owner'
    assert client.post('/api/admin/team/invite', json={'email': 'dev@gmail.com', 'role': 'Support'}, headers=h).status_code == 422
    assert client.post('/api/admin/team/invite', json={'email': 'boss@theowncollab.com', 'role': 'Owner'}, headers=h).status_code == 422
    m = client.post('/api/admin/team/invite', json={'email': 'Dev.Kumar@theowncollab.com', 'role': 'Support'}, headers=h).json()
    assert m['email'] == 'dev.kumar@theowncollab.com' and m['name'] == 'Dev Kumar' and m['invited'] is True
    assert mails[-1]['to'] == 'dev.kumar@theowncollab.com'
    assert client.post('/api/admin/team/invite', json={'email': 'dev.kumar@theowncollab.com', 'role': 'Support'}, headers=h).status_code == 409
    team = client.get('/api/admin/team', headers=staff('Support', 's@theowncollab.com')).json()
    assert team[0]['role'] == 'Owner'
    owner_id = team[0]['id']
    assert client.patch(f"/api/admin/team/{m['id']}", json={'role': 'Moderator'}, headers=h).json()['role'] == 'Moderator'
    assert client.patch(f"/api/admin/team/{m['id']}", json={'role': 'Owner'}, headers=h).status_code == 422
    assert client.patch(f'/api/admin/team/{owner_id}', json={'role': 'Support'}, headers=h).status_code == 403
    assert client.delete(f'/api/admin/team/{owner_id}', headers=h).status_code == 403
    # Another Owner-level manager can't remove themselves either
    db['ADMIN']['TEAM'].update_one({'email': 'dev.kumar@theowncollab.com'}, {'$set': {'role': 'Operations'}})
    assert client.delete(f"/api/admin/team/{m['id']}", headers=h).json() == {'ok': True}
    assert db['ADMIN']['TEAM'].count_documents({'email': 'dev.kumar@theowncollab.com'}) == 0
    actions = [e['action'] for e in _audit(db)]
    assert actions == ['Invited team member', 'Changed team role', 'Removed team member']


def test_cannot_change_or_remove_self(client, make_account, auth, db):
    acc = make_account('ops@theowncollab.com', 'brand')
    db['ADMIN']['TEAM'].insert_one({'email': 'ops@theowncollab.com', 'name': 'Ops', 'role': 'Owner'})
    mid = str(db['ADMIN']['TEAM'].find_one({'email': 'ops@theowncollab.com'})['_id'])
    other = make_account('lead@theowncollab.com', 'brand')
    db['ADMIN']['TEAM'].insert_one({'email': 'lead@theowncollab.com', 'name': 'Lead', 'role': 'Operations'})
    lead_id = str(db['ADMIN']['TEAM'].find_one({'email': 'lead@theowncollab.com'})['_id'])
    # Operations can't manage the team at all
    assert client.delete(f'/api/admin/team/{mid}', headers=auth(other)).status_code == 403
    # Owner removing themselves is blocked (Owner rule), and changing their own role too
    assert client.patch(f'/api/admin/team/{mid}', json={'role': 'Support'}, headers=auth(acc)).status_code == 403
    assert client.delete(f'/api/admin/team/{mid}', headers=auth(acc)).status_code == 403
    assert client.patch(f'/api/admin/team/{lead_id}', json={'role': 'Support'}, headers=auth(acc)).json()['role'] == 'Support'


# ── Audit ───────────────────────────────────────────────────────────────
def test_audit_json_filters_and_csv(client, staff, db):
    db['ADMIN']['AUDIT'].insert_many([
        {'actor': 'Kabir', 'action': 'Suspended account', 'target': 'Rohit Bansal', 'at': '2026-11-10T10:00:00Z'},
        {'actor': 'Dev', 'action': 'Approved verification', 'target': 'StyleKart, "verified"', 'at': '2026-11-12T12:00:00Z'},
    ])
    h = staff('Finance')
    entries = client.get('/api/admin/audit', headers=h).json()
    assert [e['actor'] for e in entries] == ['Dev', 'Kabir']
    assert set(entries[0]) == {'id', 'actor', 'action', 'target', 'at'}
    assert [e['actor'] for e in client.get('/api/admin/audit?actor=Kabir', headers=h).json()] == ['Kabir']
    assert [e['actor'] for e in client.get('/api/admin/audit?q=stylekart', headers=h).json()] == ['Dev']
    r = client.get('/api/admin/audit?format=csv', headers=h)
    assert r.headers['content-type'].startswith('text/csv') and 'attachment' in r.headers['content-disposition']
    lines = r.text.strip().splitlines()
    assert lines[0] == 'When,Who,Action,Details'
    assert lines[1] == '2026-11-12T12:00:00Z,Dev,Approved verification,"StyleKart, ""verified"""'


def test_approve_social_check_records_followers(client, make_account, staff, db):
    from utils.helpers_ import col
    from database import schema
    pid = make_account('moj@email.com', 'creator', socials=[{'platform': 'moj', 'handle': '@m', 'followers': 0, 'verified': False, 'pending': True}])
    rid = col(schema.VERIFICATION).insert_one({'personId': pid, 'name': 'Moj Person', 'type': 'creator', 'kind': 'social', 'platform': 'moj', 'handle': '@m', 'submitted': '2026-11-17T09:00:00Z', 'checks': []}).inserted_id
    r = client.post(f'/api/admin/verification/{rid}/approve', headers=staff('Operations'), json={'reason': 'Checked the profile by hand', 'followers': 21000})
    assert r.status_code == 200
    acc = col(schema.USERS).find_one({'email': 'moj@email.com'})
    moj = acc['socials'][0]
    assert moj['verified'] is True and moj['followers'] == 21000
    note = col(schema.NOTIFICATIONS).find_one({'accountId': pid})
    assert note['text'] == 'Your Moj account is verified.'
