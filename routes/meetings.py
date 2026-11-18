"""
Website "Schedule a meet" (public, no sign-in). Replaces the Google Apps Script.

GET  /api/meetings/slots   tomorrow's 30-minute slots, 9 am to 11 pm IST, with which are free
POST /api/meetings/book    book one of them; the team emails the meeting link later

Bookings are stored in MEET/SCHEDULED_MEETS in the format the team console already
reads, plus the details below. See routes/admin_meetings.py for the team side.
"""
import os
import re
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from database import schema
from utils import email_
from utils.helpers_ import col, iso, now
from utils.meetings_ import DAY_SLOTS, bookable_date, label, link_from_email, slot_end

router = APIRouter(prefix='/api/meetings')

EMAIL_RE = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]{2,}$')
PHONE_RE = re.compile(r'^\+?[\d\s-]{8,16}$')
USER_TYPES = {'creator': 'Creator', 'brand': 'Brand', 'event_partner': 'Event partner', 'other': 'Other'}
MAX_REQUESTS_PER_EMAIL = 2  # per bookable day


def _taken(date: str) -> set[str]:
    taken = set()
    for doc in col(schema.MEET_BOOKINGS).find({'date': date}):
        value = doc.get('time_slot')
        taken |= set(value if isinstance(value, list) else [value])
    return taken


@router.get('/slots')
async def slots():
    """Tomorrow (IST) only, 9:00 am to 11:00 pm IST, 30 minutes each."""
    date = bookable_date()
    taken = _taken(date)
    return {
        'date': date,
        'timezone': 'Asia/Kolkata',
        'slots': [{'time': t, 'end': slot_end(t), 'label': label(t), 'available': t not in taken} for t in DAY_SLOTS],
    }


class BookBody(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: str = Field(max_length=200)
    phone: Optional[str] = Field(default=None, max_length=20)
    userType: Literal['creator', 'brand', 'event_partner', 'other']
    company: Optional[str] = Field(default=None, max_length=150)
    topic: str = Field(min_length=10, max_length=1000)
    date: str
    time: str
    # Hidden field real people never fill in; bots usually do.
    website: Optional[str] = None


@router.post('/book')
async def book(body: BookBody, bg: BackgroundTasks):
    if body.website:
        raise HTTPException(400, 'Could not book this meeting.')
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(422, 'Enter a valid email address. We send the meeting link there.')
    phone = (body.phone or '').strip()
    if phone and not PHONE_RE.match(phone):
        raise HTTPException(422, 'Enter a valid phone number, or leave it empty.')

    date = bookable_date()
    if body.date != date:
        raise HTTPException(409, 'Meetings can only be booked for tomorrow. Refresh the page to see tomorrow’s times.')
    if body.time not in DAY_SLOTS:
        raise HTTPException(422, 'Pick one of the times shown (9:00 am to 11:00 pm IST).')
    if body.time in _taken(date):
        raise HTTPException(409, 'That time was just taken. Pick another one.')
    if col(schema.MEET_BOOKINGS).count_documents({'date': date, 'email': email, 'source': 'website'}) >= MAX_REQUESTS_PER_EMAIL:
        raise HTTPException(429, 'You already have a meeting request for tomorrow. We’ll email you the link.')

    doc = {
        # Fields the team console and the old admin_meet_controls tool read
        'date': date,
        'time_slot': body.time,
        'name': body.name.strip(),
        'emails': email,
        'user_type': USER_TYPES[body.userType],
        # Booking details
        'email': email,
        'phone': phone,
        'company': (body.company or '').strip(),
        'topic': body.topic.strip(),
        'source': 'website',
        'bookedAt': iso(),
        'linkSent': False,
    }
    col(schema.MEET_BOOKINGS).insert_one(doc)

    # Tell the team inbox there is a new request (the visitor gets the link later, by hand).
    team_inbox = os.getenv('SMTP_USER')
    if team_inbox:
        bg.add_task(
            email_.send_email_async,
            to_=team_inbox,
            from_=team_inbox,
            subject_=f"New meeting request: {doc['name']}, {date} {label(body.time)} IST",
            body_=(f"<p><b>{doc['name']}</b> ({doc['user_type']}) booked {date} at {label(body.time)} IST.</p>"
                   f"<p>Email: {email}<br>Phone: {phone or '-'}<br>Company or handle: {doc['company'] or '-'}</p>"
                   f"<p>Topic: {doc['topic']}</p><p>Send the meeting link, then mark it sent in the team console (Meetings).</p>"),
        )
    return {
        'date': date,
        'time': body.time,
        'label': label(body.time),
        'timezone': 'Asia/Kolkata',
        'fromEmail': link_from_email(),
        'message': f"Your meeting request for {label(body.time)} IST tomorrow is in. We’ll email the meeting link to {email} from {link_from_email()} before your meeting.",
        'requestedAt': iso(now()),
    }
