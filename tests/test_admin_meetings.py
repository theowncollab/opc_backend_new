"""Team console meetings (same MEET data as admin_meet_controls)."""
DATE = '2026-11-18'


def _seed(db):
    db['MEET']['TIMINGS'].insert_one({'time_slots': ['10:00', '10:30', '11:00', '15:00']})
    db['MEET']['SCHEDULED_MEETS'].insert_many([
        # Booking made by the old tool's "add meeting" form
        {'name': 'Rahul Verma', 'emails': 'rahul@fitfuel.co.in', 'user_type': 'Brand', 'date': DATE, 'time_slot': '10:00',
         'google_meet_link': 'https://meet.google.com/x', 'created_at': '2026-11-10T00:00:00Z'},
        # Block made by the old tool's "cancel timing" form
        {'name': 'cancel', 'emails': 'ceo@theowncollab.com', 'user_type': 'admin', 'date': DATE, 'time_slot': '11:00',
         'google_meet_link': '', 'created_at': ''},
    ])


def test_needs_meetings_permission(client, make_account, auth, staff):
    uid = make_account('x@email.com', 'creator')
    assert client.get(f'/api/admin/meetings?date={DATE}', headers=auth(uid)).status_code == 403
    assert client.get(f'/api/admin/meetings?date={DATE}', headers=staff('Finance')).status_code == 403
    assert client.get(f'/api/admin/meetings?date={DATE}', headers=staff('Support')).status_code == 200


def _slot(slots, time):
    return next(x for x in slots if x['time'] == time)


def test_statuses_match_old_tool(client, staff, db):
    _seed(db)
    slots = client.get(f'/api/admin/meetings?date={DATE}', headers=staff('Support')).json()
    # Every day has the fixed 9:00 am to 11:00 pm IST slots (the old TIMINGS list is ignored)
    assert [x['time'] for x in slots][:2] == ['09:00', '09:30'] and slots[-1]['time'] == '22:30' and len(slots) == 28
    booked = _slot(slots, '10:00')
    assert booked['status'] == 'booked' and booked['with'] == {'name': 'Rahul Verma', 'email': 'rahul@fitfuel.co.in', 'type': 'Brand'}
    assert booked['booking']['meetLink'] == 'https://meet.google.com/x'
    assert _slot(slots, '10:30') == {'time': '10:30', 'status': 'open'}
    assert _slot(slots, '11:00') == {'time': '11:00', 'status': 'blocked'}
    assert client.get('/api/admin/meetings?date=18-11-2026', headers=staff('Support', 's2@theowncollab.com')).status_code == 422


def test_block_reopen_add(client, staff, db):
    _seed(db)
    h = staff('Operations')
    slots = client.post('/api/admin/meetings/block', json={'date': DATE, 'time': '10:30'}, headers=h).json()
    assert _slot(slots, '10:30')['status'] == 'blocked'
    # Stored in the old tool's format so it treats the slot as taken
    doc = db['MEET']['SCHEDULED_MEETS'].find_one({'date': DATE, 'time_slot': '10:30'})
    assert doc['name'] == 'cancel' and doc['user_type'] == 'admin'
    assert client.post('/api/admin/meetings/block', json={'date': DATE, 'time': '10:00'}, headers=h).status_code == 409
    assert client.post('/api/admin/meetings/reopen', json={'date': DATE, 'time': '10:00'}, headers=h).status_code == 409
    slots = client.post('/api/admin/meetings/reopen', json={'date': DATE, 'time': '11:00'}, headers=h).json()
    assert _slot(slots, '11:00')['status'] == 'open'
    assert client.post('/api/admin/meetings/reopen', json={'date': DATE, 'time': '11:00'}, headers=h).status_code == 409
    # Extra slots outside the usual hours, for that day only
    slots = client.post('/api/admin/meetings/add-slot', json={'date': DATE, 'time': '08:30'}, headers=h).json()
    assert slots[0] == {'time': '08:30', 'status': 'open'}
    assert client.post('/api/admin/meetings/add-slot', json={'date': DATE, 'time': '08:30'}, headers=h).status_code == 409
    assert client.post('/api/admin/meetings/add-slot', json={'date': DATE, 'time': '10:00'}, headers=h).status_code == 409
    assert client.post('/api/admin/meetings/add-slot', json={'date': DATE, 'time': '25:00'}, headers=h).status_code == 422
    other = client.get('/api/admin/meetings?date=2026-11-19', headers=h).json()
    assert other[0]['time'] == '09:00' and len(other) == 28
    actions = [e['action'] for e in db['ADMIN']['AUDIT'].find()]
    assert actions == ['Blocked meeting slot', 'Reopened meeting slot', 'Added meeting slot']


def test_cancel_emails_person(client, staff, mails, db):
    _seed(db)
    h = staff('Support')
    assert client.post('/api/admin/meetings/cancel', json={'date': DATE, 'time': '10:00', 'reason': ''}, headers=h).status_code == 422
    assert client.post('/api/admin/meetings/cancel', json={'date': DATE, 'time': '11:00', 'reason': 'Team offsite'}, headers=h).status_code == 404
    slots = client.post('/api/admin/meetings/cancel', json={'date': DATE, 'time': '10:00', 'reason': 'Team offsite that day'}, headers=h).json()
    assert _slot(slots, '10:00') == {'time': '10:00', 'status': 'open'}
    assert mails[-1]['to'] == 'rahul@fitfuel.co.in' and 'Team offsite that day' in mails[-1]['body']
    assert 'Rahul Verma' in db['ADMIN']['AUDIT'].find_one({'action': 'Cancelled meeting'})['target']


def test_list_valued_time_slots(client, staff, db):
    """Older docs may hold several slots in one record."""
    db['MEET']['SCHEDULED_MEETS'].insert_one({'name': 'cancel', 'date': DATE, 'time_slot': ['10:00', '10:30']})
    h = staff('Support')
    slots = client.get(f'/api/admin/meetings?date={DATE}', headers=h).json()
    assert [_slot(slots, t)['status'] for t in ('10:00', '10:30')] == ['blocked', 'blocked']
    slots = client.post('/api/admin/meetings/reopen', json={'date': DATE, 'time': '10:00'}, headers=h).json()
    assert [_slot(slots, t)['status'] for t in ('10:00', '10:30')] == ['open', 'blocked']


def test_email(client, staff, mails):
    h = staff('Support')
    assert client.post('/api/admin/meetings/email', json={'to': 'bad', 'subject': 'Hi', 'body': 'x'}, headers=h).status_code == 422
    assert client.post('/api/admin/meetings/email', json={'to': 'a@b.co', 'subject': 'Hi', 'body': 'See you\nsoon'}, headers=h).json() == {'sent': True}
    assert mails[-1] == {'to': 'a@b.co', 'from': 'noreply@theowncollab.com', 'subject': 'Hi', 'body': 'See you<br>soon'}
