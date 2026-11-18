"""Website "Schedule a meet": tomorrow only (IST), 9 am to 11 pm IST, team marks the link as sent."""
from datetime import datetime

from utils import meetings_


def _form(**over):
    body = {'name': 'Rahul Verma', 'email': 'Rahul@FitFuel.co.in', 'phone': '+91 98200 11223', 'userType': 'brand',
            'company': 'FitFuel Nutrition', 'topic': 'We want to run a creator campaign for our protein bars.',
            'date': meetings_.bookable_date(), 'time': '19:30'}
    body.update(over)
    return body


def test_tomorrow_in_ist(monkeypatch):
    # 11:50 pm IST on 17 Nov is still 17 Nov in India (UTC is 18:20), so tomorrow = 18 Nov
    monkeypatch.setattr(meetings_, 'now_ist', lambda: datetime(2026, 11, 17, 23, 50, tzinfo=meetings_.IST))
    assert meetings_.bookable_date() == '2026-11-18'
    # Ten minutes past midnight IST (still 17 Nov in UTC) the bookable day moves on
    monkeypatch.setattr(meetings_, 'now_ist', lambda: datetime(2026, 11, 18, 0, 10, tzinfo=meetings_.IST))
    assert meetings_.bookable_date() == '2026-11-19'


def test_slots_are_tomorrow_9am_to_11pm_ist(client, db):
    r = client.get('/api/meetings/slots').json()
    assert r['date'] == meetings_.bookable_date() and r['timezone'] == 'Asia/Kolkata'
    slots = r['slots']
    assert len(slots) == 28
    assert slots[0] == {'time': '09:00', 'end': '09:30', 'label': '9:00 am', 'available': True}
    assert slots[-1] == {'time': '22:30', 'end': '23:00', 'label': '10:30 pm', 'available': True}
    # Blocked by the team or already booked: not available
    db['MEET']['SCHEDULED_MEETS'].insert_one({'name': 'cancel', 'date': r['date'], 'time_slot': '12:00', 'blocked': True})
    taken = {s['time'] for s in client.get('/api/meetings/slots').json()['slots'] if not s['available']}
    assert taken == {'12:00'}


def test_booking_stores_details_and_tells_the_team(client, db, mails):
    r = client.post('/api/meetings/book', json=_form())
    assert r.status_code == 200
    body = r.json()
    assert body['label'] == '7:30 pm' and 'rahul@fitfuel.co.in' in body['message'] and body['fromEmail'] in body['message']
    doc = db['MEET']['SCHEDULED_MEETS'].find_one({'source': 'website'})
    assert doc['email'] == 'rahul@fitfuel.co.in' and doc['user_type'] == 'Brand' and doc['company'] == 'FitFuel Nutrition'
    assert doc['date'] == meetings_.bookable_date() and doc['time_slot'] == '19:30' and doc['linkSent'] is False
    assert mails and 'New meeting request' in mails[-1]['subject'] and '7:30 pm IST' in mails[-1]['subject']
    slot = next(s for s in client.get('/api/meetings/slots').json()['slots'] if s['time'] == '19:30')
    assert slot['available'] is False


def test_booking_refusals(client):
    assert client.post('/api/meetings/book', json=_form(date='2030-01-01')).status_code == 409
    assert client.post('/api/meetings/book', json=_form(time='08:30')).status_code == 422
    assert client.post('/api/meetings/book', json=_form(time='23:00')).status_code == 422
    assert client.post('/api/meetings/book', json=_form(email='not-an-email')).status_code == 422
    assert client.post('/api/meetings/book', json=_form(phone='abc')).status_code == 422
    assert client.post('/api/meetings/book', json=_form(topic='short')).status_code == 422
    assert client.post('/api/meetings/book', json=_form(website='http://spam')).status_code == 400
    assert client.post('/api/meetings/book', json=_form()).status_code == 200
    taken = client.post('/api/meetings/book', json=_form(email='other@x.com'))
    assert taken.status_code == 409 and 'just taken' in taken.json()['detail']
    assert client.post('/api/meetings/book', json=_form(time='20:00')).status_code == 200
    # Third request from the same email for the same day
    assert client.post('/api/meetings/book', json=_form(time='21:00')).status_code == 429


def test_team_sees_requests_and_marks_link_sent(client, staff, db):
    client.post('/api/meetings/book', json=_form())
    h = staff('Support')
    pending = client.get('/api/admin/meetings/bookings?status=pending', headers=h).json()
    assert len(pending) == 1
    b = pending[0]
    assert b['name'] == 'Rahul Verma' and b['phone'] == '+91 98200 11223' and b['topic'].startswith('We want') and b['label'] == '7:30 pm'
    assert b['linkSent'] is False

    assert client.post(f"/api/admin/meetings/bookings/{b['id']}/link-sent", json={'meetLink': 'meet.google.com/abc'}, headers=h).status_code == 422
    sent = client.post(f"/api/admin/meetings/bookings/{b['id']}/link-sent", json={'meetLink': 'https://meet.google.com/abc-defg-hij'}, headers=h).json()
    assert sent['linkSent'] is True and sent['linkSentBy'] == 'Support' and sent['meetLink'] == 'https://meet.google.com/abc-defg-hij'
    assert client.get('/api/admin/meetings/bookings?status=pending', headers=h).json() == []
    assert len(client.get('/api/admin/meetings/bookings?status=sent', headers=h).json()) == 1
    assert db['ADMIN']['AUDIT'].find_one({'action': 'Sent meeting link'})

    undone = client.post(f"/api/admin/meetings/bookings/{b['id']}/link-not-sent", json={}, headers=h).json()
    assert undone['linkSent'] is False and undone['linkSentBy'] is None

    # The day view shows the full request on the booked slot
    day = client.get(f"/api/admin/meetings?date={b['date']}", headers=h).json()
    slot = next(s for s in day if s['time'] == '19:30')
    assert slot['status'] == 'booked' and slot['booking']['email'] == 'rahul@fitfuel.co.in'
    assert client.get('/api/admin/meetings/bookings', headers=staff('Finance')).status_code == 403
