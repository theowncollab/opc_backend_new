"""
Team console: "Schedule a meet" slots (DASHBOARD_API.md, section D, Meetings).

Reads and writes the same MEET database as backend/admin_meet_controls, in its
format, so both tools agree while the old one is retired:
  Default slots for every day: utils/meetings_.DAY_SLOTS (9:00 am to 11:00 pm IST, 30 min).
  (TIMINGS[0].time_slots, the old tool's list, is no longer used.)
  SCHEDULED_MEETS {date, time_slot, name, emails, user_type, google_meet_link, created_at}
      name == 'cancel' (or blocked: true, or no name) -> slot is blocked
      anything else                                  -> slot is booked by that person
  EXTRA_SLOTS {date, time_slot}   slots added for one day only
"""
import os
import re

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel

from database import schema
from utils import email_
from utils.deps_ import require
from utils.helpers_ import audit, col, iso, oid
from utils.meetings_ import DAY_SLOTS, label

router = APIRouter(prefix='/api/admin/meetings')

DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
TIME_RE = re.compile(r'^([01]\d|2[0-3]):[0-5]\d$')
EMAIL_RE = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')


class SlotBody(BaseModel):
    date: str = ''
    time: str = ''


class CancelBody(SlotBody):
    reason: str = ''


class EmailBody(BaseModel):
    to: str = ''
    subject: str = ''
    body: str = ''


def _check_date(date: str) -> str:
    if not DATE_RE.match(date or ''):
        raise HTTPException(422, 'Give the date as YYYY-MM-DD.')
    return date


def _check_slot(body: SlotBody) -> tuple[str, str]:
    _check_date(body.date)
    if not TIME_RE.match(body.time or ''):
        raise HTTPException(422, 'Give the time as HH:MM, for example 10:30.')
    return body.date, body.time


def _slot_times(doc) -> list[str]:
    value = doc.get('time_slot')
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)] if value else []


def _is_blocked(doc: dict) -> bool:
    return bool(doc.get('blocked')) or not doc.get('name') or doc.get('name') == 'cancel'


def _bookings(date: str) -> dict[str, dict]:
    """time -> booking doc for that date."""
    out = {}
    for doc in col(schema.MEET_BOOKINGS).find({'date': date}):
        for t in _slot_times(doc):
            out[t] = doc
    return out


def _day_slots(date: str) -> list[dict]:
    times = set(DAY_SLOTS)
    times |= {str(d['time_slot']) for d in col(schema.MEET_EXTRA).find({'date': date})}
    bookings = _bookings(date)
    times |= set(bookings)
    slots = []
    for t in sorted(times):
        doc = bookings.get(t)
        if not doc:
            slots.append({'time': t, 'status': 'open'})
        elif _is_blocked(doc):
            slots.append({'time': t, 'status': 'blocked'})
        else:
            slots.append({
                'time': t,
                'status': 'booked',
                'with': {'name': doc.get('name', ''), 'email': doc.get('emails') or doc.get('email', ''), 'type': doc.get('user_type', '')},
                'booking': _booking_out(doc),
            })
    return slots


def _booking_out(doc: dict) -> dict:
    """A website booking request, with everything the visitor gave and whether the link was sent."""
    time = _slot_times(doc)[0] if _slot_times(doc) else ''
    return {
        'id': str(doc['_id']),
        'date': doc.get('date', ''),
        'time': time,
        'label': label(time) if TIME_RE.match(time) else time,
        'name': doc.get('name', ''),
        'email': doc.get('email') or doc.get('emails') or '',
        'phone': doc.get('phone', ''),
        'userType': doc.get('user_type', ''),
        'company': doc.get('company', ''),
        'topic': doc.get('topic', ''),
        'bookedAt': doc.get('bookedAt') or doc.get('created_at') or '',
        'linkSent': bool(doc.get('linkSent')),
        'linkSentAt': doc.get('linkSentAt'),
        'linkSentBy': doc.get('linkSentBy'),
        'meetLink': doc.get('meetLink') or doc.get('google_meet_link') or '',
    }


def _remove_booking(date: str, time: str, doc: dict) -> None:
    """Delete one slot from a booking doc (old docs may hold a list of slots)."""
    times = _slot_times(doc)
    if len(times) > 1:
        col(schema.MEET_BOOKINGS).update_one({'_id': doc['_id']}, {'$set': {'time_slot': [t for t in times if t != time]}})
    else:
        col(schema.MEET_BOOKINGS).delete_one({'_id': doc['_id']})


def _send(bg: BackgroundTasks, to: str, subject: str, body: str) -> None:
    bg.add_task(email_.send_email_async, to_=to, from_=os.getenv('SMTP_USER'), subject_=subject, body_=body)


@router.get('')
async def list_slots(date: str = Query(''), member: dict = Depends(require('meetings.manage'))):
    """Every slot for one day, with its status and who booked it."""
    return _day_slots(_check_date(date))


@router.post('/block')
async def block_slot(body: SlotBody, member: dict = Depends(require('meetings.manage'))):
    date, time = _check_slot(body)
    status = next((s['status'] for s in _day_slots(date) if s['time'] == time), None)
    if status in ('booked', 'blocked'):
        raise HTTPException(409, f'The {time} slot on {date} is already {status}.')
    col(schema.MEET_BOOKINGS).insert_one({
        'name': 'cancel', 'emails': '', 'user_type': 'admin', 'date': date, 'time_slot': time,
        'google_meet_link': '', 'created_at': '', 'blocked': True,
    })
    audit(member['name'], 'Blocked meeting slot', f'{date} {time}')
    return _day_slots(date)


@router.post('/reopen')
async def reopen_slot(body: SlotBody, member: dict = Depends(require('meetings.manage'))):
    date, time = _check_slot(body)
    doc = _bookings(date).get(time)
    if not doc:
        raise HTTPException(409, f'The {time} slot on {date} is already open.')
    if not _is_blocked(doc):
        raise HTTPException(409, 'Someone booked this slot. Cancel the meeting instead.')
    _remove_booking(date, time, doc)
    audit(member['name'], 'Reopened meeting slot', f'{date} {time}')
    return _day_slots(date)


@router.post('/cancel')
async def cancel_meeting(body: CancelBody, bg: BackgroundTasks, member: dict = Depends(require('meetings.manage'))):
    date, time = _check_slot(body)
    reason = (body.reason or '').strip()
    if len(reason) < 5:
        raise HTTPException(422, 'Give a reason of at least 5 characters. It is sent to the person.')
    doc = _bookings(date).get(time)
    if not doc or _is_blocked(doc):
        raise HTTPException(404, f'There is no meeting booked at {time} on {date}.')
    _remove_booking(date, time, doc)
    to = doc.get('emails') or doc.get('email')
    if to:
        _send(
            bg, to, 'Your OPC meeting has been cancelled',
            f"<p>Hello {doc.get('name', '')},</p><p>Your OPC meeting on {date} at {time} has been cancelled.</p>"
            f"<p>Reason: {reason}</p><p>You can book a new time at theowncollab.com/schedule-a-meet.</p><p>The OPC team</p>",
        )
    audit(member['name'], 'Cancelled meeting', f"{date} {time} with {doc.get('name', '')}: {reason}")
    return _day_slots(date)


@router.post('/add-slot')
async def add_slot(body: SlotBody, member: dict = Depends(require('meetings.manage'))):
    date, time = _check_slot(body)
    if any(s['time'] == time for s in _day_slots(date)):
        raise HTTPException(409, f'There is already a {time} slot on {date}.')
    col(schema.MEET_EXTRA).insert_one({'date': date, 'time_slot': time})
    audit(member['name'], 'Added meeting slot', f'{date} {time}')
    return _day_slots(date)


@router.post('/email')
async def email_person(body: EmailBody, bg: BackgroundTasks, member: dict = Depends(require('meetings.manage'))):
    if not EMAIL_RE.match((body.to or '').strip()):
        raise HTTPException(422, 'Enter a valid email address.')
    if not body.subject.strip() or not body.body.strip():
        raise HTTPException(422, 'Add a subject and a message.')
    _send(bg, body.to.strip(), body.subject.strip(), body.body.strip().replace('\n', '<br>'))
    audit(member['name'], 'Sent email', f'{body.to.strip()}: {body.subject.strip()}')
    return {'sent': True}


# ── Booking requests from the website ───────────────────────────────────
class LinkSentBody(BaseModel):
    meetLink: str = ''


@router.get('/bookings')
async def list_bookings(status: str = Query('all'), member: dict = Depends(require('meetings.manage'))):
    """Meeting requests people made on the website, soonest first. status = pending | sent | all."""
    query: dict = {'name': {'$nin': ['cancel', '', None]}, 'blocked': {'$ne': True}}
    if status == 'pending':
        query['linkSent'] = {'$ne': True}
    elif status == 'sent':
        query['linkSent'] = True
    docs = [d for d in col(schema.MEET_BOOKINGS).find(query)]
    out = [_booking_out(d) for d in docs]
    return sorted(out, key=lambda b: (b['date'], b['time']))


def _get_booking(booking_id: str) -> dict:
    doc = col(schema.MEET_BOOKINGS).find_one({'_id': oid(booking_id)})
    if not doc or _is_blocked(doc):
        raise HTTPException(404, 'This meeting request no longer exists.')
    return doc


@router.post('/bookings/{booking_id}/link-sent')
async def mark_link_sent(booking_id: str, body: LinkSentBody, member: dict = Depends(require('meetings.manage'))):
    """The team emailed the meeting link by hand; record who and when (and the link, if given)."""
    doc = _get_booking(booking_id)
    link = (body.meetLink or '').strip()
    if link and not link.startswith('https://'):
        raise HTTPException(422, 'The meeting link should start with https://')
    col(schema.MEET_BOOKINGS).update_one({'_id': doc['_id']}, {'$set': {
        'linkSent': True, 'linkSentAt': iso(), 'linkSentBy': member.get('name', ''), 'meetLink': link or doc.get('meetLink', ''),
    }})
    audit(member['name'], 'Sent meeting link', f"{doc.get('name', '')} ({doc.get('email') or doc.get('emails')}), {doc.get('date')} {_slot_times(doc)[0] if _slot_times(doc) else ''}")
    return _booking_out(col(schema.MEET_BOOKINGS).find_one({'_id': doc['_id']}))


@router.post('/bookings/{booking_id}/link-not-sent')
async def unmark_link_sent(booking_id: str, member: dict = Depends(require('meetings.manage'))):
    """Undo, if it was marked by mistake."""
    doc = _get_booking(booking_id)
    col(schema.MEET_BOOKINGS).update_one({'_id': doc['_id']}, {'$set': {'linkSent': False, 'linkSentAt': None, 'linkSentBy': None}})
    audit(member['name'], 'Marked meeting link as not sent', f"{doc.get('name', '')}, {doc.get('date')}")
    return _booking_out(col(schema.MEET_BOOKINGS).find_one({'_id': doc['_id']}))
