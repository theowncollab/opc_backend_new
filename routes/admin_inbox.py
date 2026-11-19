"""
Website inbox: what visitors send through the public site, for the OPC team.

Public (no sign-in):
  POST /api/newsletter                  footer "Subscribe" (saves the address)

Team console (needs the `support.reply` permission):
  GET  /api/admin/inbox/messages        "Contact us" messages, newest first
  POST /api/admin/inbox/messages/{id}/reply    email the sender from OPC, saved on the message
  POST /api/admin/inbox/messages/{id}/status   new / closed
  GET  /api/admin/inbox/events          "Register an event" submissions, newest first
  POST /api/admin/inbox/events/{id}/status     new / contacted / listed / declined, with a note
  GET  /api/admin/inbox/newsletter      subscribers (?format=csv to download)
  POST /api/admin/inbox/newsletter/{id}/remove  unsubscribe someone

The contact form itself (routes/contact_us.py) saves each message here as well as
emailing it to the team inbox.
"""
import csv
import io
import os
import re
from datetime import datetime
from html import escape
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from database import schema
from utils import email_
from utils.deps_ import require
from utils.helpers_ import audit, col, iso, oid

router = APIRouter()

EMAIL = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]{2,}$')


def _actor(member: dict) -> str:
    return member.get('name') or member.get('email', 'OPC team')


def _stamp(value) -> str:
    """Dates may be ISO strings or datetimes (older event registrations)."""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or '')


def _newest(items: list, key: str) -> list:
    return sorted(items, key=lambda d: _stamp(d.get(key)), reverse=True)


def _get(where: tuple, item_id: str, what: str) -> dict:
    doc = col(where).find_one({'_id': oid(item_id)})
    if not doc:
        raise HTTPException(404, f'{what} not found.')
    return doc


# ── Newsletter (public) ──────────────────────────────────────────────────
class NewsletterBody(BaseModel):
    email: str = Field(max_length=200)
    website: Optional[str] = None  # left empty by people; bots tend to fill it in


@router.post('/api/newsletter')
async def subscribe(body: NewsletterBody):
    """Footer sign-up. Signing up twice is fine: it just says you're on the list."""
    if body.website:
        return {'ok': True, 'message': 'You’re subscribed.'}  # quietly ignore bots
    address = body.email.strip().lower()
    if not EMAIL.match(address):
        raise HTTPException(422, 'Enter a valid email address.')
    existing = col(schema.NEWSLETTER).find_one({'email': address})
    if existing and existing.get('status') == 'subscribed':
        return {'ok': True, 'message': 'You’re already on the list.'}
    if existing:
        col(schema.NEWSLETTER).update_one({'_id': existing['_id']},
                                          {'$set': {'status': 'subscribed', 'subscribedAt': iso()}, '$unset': {'removedAt': '', 'removedBy': ''}})
    else:
        col(schema.NEWSLETTER).insert_one({'email': address, 'subscribedAt': iso(), 'source': 'footer', 'status': 'subscribed'})
    return {'ok': True, 'message': 'You’re subscribed. We’ll write now and then about new campaigns and events.'}


# ── Contact messages ─────────────────────────────────────────────────────
def save_contact_message(name: str, email: str, subject: str, message: str) -> None:
    """Called by the public contact form."""
    col(schema.CONTACT_MESSAGES).insert_one({
        'name': name.strip()[:200], 'email': email.strip()[:200], 'subject': subject.strip()[:300],
        'message': message.strip()[:5000], 'receivedAt': iso(), 'status': 'new', 'replies': [],
    })


def _message_out(m: dict) -> dict:
    return {
        'id': str(m['_id']), 'name': m.get('name', ''), 'email': m.get('email', ''), 'subject': m.get('subject', ''),
        'message': m.get('message', ''), 'receivedAt': _stamp(m.get('receivedAt')), 'status': m.get('status', 'new'),
        'replies': [{'by': r.get('by', ''), 'at': r.get('at', ''), 'text': r.get('text', '')} for r in m.get('replies') or []],
    }


class InboxReply(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


class MessageStatus(BaseModel):
    status: Literal['new', 'closed']


@router.get('/api/admin/inbox/messages')
async def list_messages(member: dict = Depends(require('support.reply'))):
    return [_message_out(m) for m in _newest(list(col(schema.CONTACT_MESSAGES).find()), 'receivedAt')]


@router.post('/api/admin/inbox/messages/{message_id}/reply')
async def reply_message(message_id: str, body: InboxReply, bg: BackgroundTasks, member: dict = Depends(require('support.reply'))):
    m = _get(schema.CONTACT_MESSAGES, message_id, 'Message')
    text = body.text.strip()
    if not text:
        raise HTTPException(422, 'Write a reply first.')
    if not EMAIL.match(m.get('email', '')):
        raise HTTPException(422, 'This message has no valid email address to reply to.')
    html = (
        f'<p>{escape(text).replace(chr(10), "<br>")}</p>'
        '<hr style="border:none;border-top:1px solid #ddd;margin:20px 0">'
        f'<p style="color:#666;font-size:13px">You wrote to OPC: <b>{escape(m.get("subject", ""))}</b><br>'
        f'{escape(m.get("message", "")).replace(chr(10), "<br>")}</p>'
    )
    bg.add_task(email_.send_email_async, to_=m['email'], from_=os.getenv('SMTP_USER'),
                subject_=f"Re: {m.get('subject') or 'Your message to OPC'}", body_=html)
    col(schema.CONTACT_MESSAGES).update_one({'_id': m['_id']}, {
        '$push': {'replies': {'by': _actor(member), 'at': iso(), 'text': text}},
        '$set': {'status': 'replied'},
    })
    audit(_actor(member), 'Replied to a contact message', f"{m.get('name', '')} ({m.get('email', '')}): {m.get('subject', '')}")
    return _message_out(col(schema.CONTACT_MESSAGES).find_one({'_id': m['_id']}))


@router.post('/api/admin/inbox/messages/{message_id}/status')
async def message_status(message_id: str, body: MessageStatus, member: dict = Depends(require('support.reply'))):
    m = _get(schema.CONTACT_MESSAGES, message_id, 'Message')
    col(schema.CONTACT_MESSAGES).update_one({'_id': m['_id']}, {'$set': {'status': body.status}})
    audit(_actor(member), 'Closed a contact message' if body.status == 'closed' else 'Reopened a contact message',
          f"{m.get('name', '')}: {m.get('subject', '')}")
    return _message_out(col(schema.CONTACT_MESSAGES).find_one({'_id': m['_id']}))


# ── Registered events ────────────────────────────────────────────────────
def _event_out(e: dict) -> dict:
    return {
        'id': str(e['_id']), 'name': e.get('name', ''), 'start': _stamp(e.get('start_date')), 'end': _stamp(e.get('end_date')),
        'organizer': e.get('organizer', ''), 'location': e.get('location', ''),
        'contactName': e.get('poc_name', ''), 'contactEmail': e.get('poc_email', ''), 'contactPhone': str(e.get('poc_phone') or ''),
        'receivedAt': _stamp(e.get('receivedAt')), 'status': e.get('status', 'new'), 'note': e.get('note', ''),
        'updatedBy': e.get('updatedBy', ''), 'updatedAt': _stamp(e.get('updatedAt')),
    }


class EventStatus(BaseModel):
    status: Literal['new', 'contacted', 'listed', 'declined']
    note: str = Field(default='', max_length=1000)


@router.get('/api/admin/inbox/events')
async def list_events(member: dict = Depends(require('support.reply'))):
    events = list(col(schema.REGISTERED_EVENTS).find())
    # Older registrations have no receivedAt: their ObjectId still records when they arrived.
    for e in events:
        if not e.get('receivedAt'):
            e['receivedAt'] = e['_id'].generation_time.isoformat() if hasattr(e['_id'], 'generation_time') else ''
    return [_event_out(e) for e in _newest(events, 'receivedAt')]


@router.post('/api/admin/inbox/events/{event_id}/status')
async def event_status(event_id: str, body: EventStatus, member: dict = Depends(require('support.reply'))):
    e = _get(schema.REGISTERED_EVENTS, event_id, 'Event')
    changes = {'status': body.status, 'updatedBy': _actor(member), 'updatedAt': iso()}
    if body.note.strip():
        changes['note'] = body.note.strip()
    col(schema.REGISTERED_EVENTS).update_one({'_id': e['_id']}, {'$set': changes})
    audit(_actor(member), f'Marked event as {body.status}', f"{e.get('name', '')} ({e.get('organizer', '')})")
    return _event_out(col(schema.REGISTERED_EVENTS).find_one({'_id': e['_id']}))


# ── Newsletter subscribers ───────────────────────────────────────────────
def _subscriber_out(s: dict) -> dict:
    return {'id': str(s['_id']), 'email': s.get('email', ''), 'subscribedAt': _stamp(s.get('subscribedAt')),
            'status': s.get('status', 'subscribed'), 'source': s.get('source', '')}


@router.get('/api/admin/inbox/newsletter')
async def list_subscribers(format: str = Query('json'), member: dict = Depends(require('support.reply'))):
    subs = [_subscriber_out(s) for s in _newest(list(col(schema.NEWSLETTER).find()), 'subscribedAt')]
    if format == 'csv':
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(['email', 'subscribed_at', 'status'])
        for s in subs:
            if s['status'] == 'subscribed':
                writer.writerow([s['email'], s['subscribedAt'], s['status']])
        audit(_actor(member), 'Downloaded newsletter list', f"{sum(1 for s in subs if s['status'] == 'subscribed')} subscribers")
        return Response(buf.getvalue(), media_type='text/csv',
                        headers={'Content-Disposition': 'attachment; filename="opc-newsletter.csv"'})
    return subs


@router.post('/api/admin/inbox/newsletter/{subscriber_id}/remove')
async def remove_subscriber(subscriber_id: str, member: dict = Depends(require('support.reply'))):
    s = _get(schema.NEWSLETTER, subscriber_id, 'Subscriber')
    col(schema.NEWSLETTER).update_one({'_id': s['_id']}, {'$set': {'status': 'unsubscribed', 'removedAt': iso(), 'removedBy': _actor(member)}})
    audit(_actor(member), 'Unsubscribed from newsletter', s.get('email', ''))
    return _subscriber_out(col(schema.NEWSLETTER).find_one({'_id': s['_id']}))
