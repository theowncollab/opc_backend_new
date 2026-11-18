"""
Chat, support tickets and notifications for creators and brands (DASHBOARD_API.md section C).

Every chat message is scanned on the server. Sharing contact details or abusive
language flags the message, pauses (suspends) the conversation and adds it to
the team's moderation queue. The dashboard's own check is only a first warning.
"""
import os
import re

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from database import schema
from utils import email_
from utils.deps_ import creator_or_brand
from utils.helpers_ import col, display_name, iso, next_code, oid, role_of

router = APIRouter()

# ── Message scanner ──────────────────────────────────────────────────────
# Extend these lists freely; every entry is matched case-insensitively.
ABUSE_WORDS = [
    'idiot', 'stupid', 'moron', 'loser', 'scammer', 'fraud', 'bastard', 'shut up',
]
OFF_PLATFORM_WORDS = ['whatsapp', 'telegram', 'wa.me', 'signal app', 'call me on', 'dm me on insta']

PHONE = re.compile(r'(?:\+?91[\s-]*)?(?:\d[\s-]*){10,}')
EMAIL = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')
ADDRESS = re.compile(
    r'\b(?:flat|house|plot|door|shop)\s*(?:no\.?|number|#)\s*\d+|\b\d+[\w/-]*\s*,?\s*\w*\s*(?:street|road|lane|nagar|marg|sector)\b',
    re.IGNORECASE,
)


def scan(text: str) -> str | None:
    """Reason a message must be flagged ('phone' | 'email' | 'address' | 'off-platform' | 'abuse'), else None."""
    lowered = text.lower()
    if PHONE.search(text):
        return 'phone'
    if EMAIL.search(text):
        return 'email'
    if ADDRESS.search(text):
        return 'address'
    if any(w in lowered for w in OFF_PLATFORM_WORDS):
        return 'off-platform'
    if any(re.search(rf'\b{re.escape(w)}\b', lowered) for w in ABUSE_WORDS):
        return 'abuse'
    return None


REASON_TEXT = {
    'phone': 'a phone number',
    'email': 'an email address',
    'address': 'an address',
    'off-platform': 'a request to move the chat off OPC',
    'abuse': 'abusive language',
}


# ── Conversation helpers ─────────────────────────────────────────────────
def _member_conversation(conv_id: str, account: dict) -> dict:
    conv = col(schema.CONVERSATIONS).find_one({'_id': oid(conv_id)})
    if not conv or str(account['_id']) not in [m['accountId'] for m in conv.get('members', [])]:
        raise HTTPException(404, 'Conversation not found.')
    return conv


def _view(conv: dict, account: dict) -> dict:
    """A conversation as the dashboard's Conversation type, seen by `account`."""
    me = str(account['_id'])
    other = next((m for m in conv['members'] if m['accountId'] != me), {'name': 'OPC'})
    messages = col(schema.MESSAGES).find({'conversationId': str(conv['_id'])}).sort('at', 1)
    return {
        'id': str(conv['_id']),
        'title': other.get('name', ''),
        'subtitle': conv.get('subject', ''),
        'unread': int((conv.get('unread') or {}).get(me, 0)),
        'flagged': bool(conv.get('flagged')),
        'suspended': bool(conv.get('suspended')),
        'lastAt': conv.get('lastAt', ''),
        'messages': [
            {
                'id': str(m['_id']),
                'from': 'system' if m['fromAccountId'] == 'system' else ('me' if m['fromAccountId'] == me else 'them'),
                'text': m['text'],
                'at': m['at'],
                'flagged': bool(m.get('flagged')),
            }
            for m in messages
        ],
    }


@router.get('/api/chat/conversations')
async def list_conversations(account: dict = Depends(creator_or_brand)):
    convs = col(schema.CONVERSATIONS).find({'members.accountId': str(account['_id'])}).sort('lastAt', -1)
    return [_view(c, account) for c in convs]


@router.get('/api/chat/conversations/{conv_id}')
async def get_conversation(conv_id: str, account: dict = Depends(creator_or_brand)):
    return _view(_member_conversation(conv_id, account), account)


@router.post('/api/chat/conversations/{conv_id}/read')
async def mark_read(conv_id: str, account: dict = Depends(creator_or_brand)):
    conv = _member_conversation(conv_id, account)
    col(schema.CONVERSATIONS).update_one({'_id': conv['_id']}, {'$set': {f"unread.{account['_id']}": 0}})
    return {'ok': True}


class SendBody(BaseModel):
    text: str


@router.post('/api/chat/conversations/{conv_id}/send')
async def send_message(conv_id: str, body: SendBody, account: dict = Depends(creator_or_brand)):
    conv = _member_conversation(conv_id, account)
    text = body.text.strip()
    if not 1 <= len(text) <= 2000:
        raise HTTPException(422, 'Messages must be between 1 and 2,000 characters.')
    if conv.get('suspended'):
        raise HTTPException(423, 'This chat is paused while OPC reviews it. Message OPC Support if it’s urgent.')

    me = str(account['_id'])
    reason = scan(text)
    at = iso()
    msg_id = col(schema.MESSAGES).insert_one(
        {'conversationId': str(conv['_id']), 'fromAccountId': me, 'text': text, 'at': at, 'flagged': bool(reason)}
    ).inserted_id

    update = {'$set': {'lastAt': at}, '$inc': {}}
    for m in conv['members']:
        if m['accountId'] != me:
            update['$inc'][f"unread.{m['accountId']}"] = 1

    if reason:
        col(schema.MESSAGES).insert_one({
            'conversationId': str(conv['_id']),
            'fromAccountId': 'system',
            'text': f'A message shared {REASON_TEXT[reason]}, so this chat is paused while OPC reviews it. '
                    'Deals and escrow are not affected.',
            'at': iso(),
            'flagged': False,
        })
        update['$set'].update({'flagged': True, 'suspended': True})
        col(schema.FLAGS).insert_one({
            'conversationId': str(conv['_id']),
            'conversation': ' ↔ '.join(m['name'] for m in conv['members']),
            'messageId': str(msg_id),
            'fromAccountId': me,
            'from': display_name(account),
            'fromType': role_of(account),
            'message': text,
            'reason': reason,
            'at': at,
            'status': 'open',
        })
        col(schema.USERS).update_one({'_id': account['_id']}, {'$inc': {'flags': 1}})
        if conv.get('dealId'):
            col(schema.DEALS).update_one({'code': conv['dealId']}, {'$set': {'flaggedChat': True}})

    if not update['$inc']:
        del update['$inc']
    col(schema.CONVERSATIONS).update_one({'_id': conv['_id']}, update)
    return _view(col(schema.CONVERSATIONS).find_one({'_id': conv['_id']}), account)


# ── Support tickets ──────────────────────────────────────────────────────
HIGH_PRIORITY = {'payment', 'paused chat'}


class TicketBody(BaseModel):
    category: str
    subject: str
    body: str


def _ticket_view(t: dict) -> dict:
    return {
        'id': t['code'],
        'subject': t['subject'],
        'status': 'closed' if t.get('status') == 'closed' else 'open',
        'date': t['opened'],
    }


@router.get('/api/support/tickets')
async def list_tickets(account: dict = Depends(creator_or_brand)):
    tickets = col(schema.TICKETS).find({'accountId': str(account['_id'])}).sort('opened', -1)
    return [_ticket_view(t) for t in tickets]


@router.post('/api/support/tickets')
async def create_ticket(body: TicketBody, background: BackgroundTasks, account: dict = Depends(creator_or_brand)):
    if not body.category.strip():
        raise HTTPException(422, 'Choose a category.')
    if not body.subject.strip():
        raise HTTPException(422, 'Add a short subject.')
    if len(body.body.strip()) < 20:
        raise HTTPException(422, 'Describe the issue in at least 20 characters.')
    ticket = {
        'code': next_code('TKT'),
        'accountId': str(account['_id']),
        'from': display_name(account),
        'fromType': role_of(account),
        'category': body.category.strip(),
        'subject': body.subject.strip(),
        'body': body.body.strip(),
        'priority': 'high' if body.category.strip().lower() in HIGH_PRIORITY else 'normal',
        'status': 'open',
        'assignee': None,
        'opened': iso(),
        'replies': [],
    }
    col(schema.TICKETS).insert_one(ticket)
    support_inbox = os.getenv('SMTP_USER')
    if support_inbox:
        background.add_task(
            email_.send_email_async,
            to_=support_inbox,
            from_=support_inbox,
            subject_=f"[{ticket['code']}] {ticket['subject']}",
            body_=(
                f"<p><b>From:</b> {ticket['from']} ({ticket['fromType']}, {account.get('email', '')})</p>"
                f"<p><b>Category:</b> {ticket['category']} &middot; <b>Priority:</b> {ticket['priority']}</p>"
                f"<p>{ticket['body']}</p>"
            ),
        )
    return _ticket_view(ticket)


# ── Notifications ────────────────────────────────────────────────────────
@router.get('/api/notifications')
async def list_notifications(account: dict = Depends(creator_or_brand)):
    items = col(schema.NOTIFICATIONS).find({'accountId': str(account['_id'])}).sort('at', -1).limit(50)
    return [{'id': str(n['_id']), 'text': n['text'], 'at': n['at'], 'read': bool(n.get('read'))} for n in items]


@router.post('/api/notifications/read')
async def read_notifications(account: dict = Depends(creator_or_brand)):
    col(schema.NOTIFICATIONS).update_many({'accountId': str(account['_id']), 'read': False}, {'$set': {'read': True}})
    return {'ok': True}
