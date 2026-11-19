"""
Team console API (DASHBOARD_API.md, section D). Every route needs an OPC team
member with the listed permission (utils/deps_.require). Every change writes the
audit log; risky actions need a written reason.

Response shapes match dashboard-app/src/admin/types.ts.
"""
import csv
import io
import os
import re
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from database import schema
from utils import email_, fees_
from utils.deps_ import require, staff_member
from utils.helpers_ import (
    MEMBER_ROLES, audit, col, display_name, handle_of, iso, notify, now, oid, parse_iso, role_of, ser, status_of,
)
from utils.permissions_ import ROLE_PERMISSIONS, TEAM_ROLES

router = APIRouter(prefix='/api/admin')

DEAL_STAGES = ['selected', 'finalised', 'signed', 'timeline', 'brief', 'script', 'scriptApproved',
               'contentMade', 'review', 'verify', 'paid']
TYPES = ['creator', 'brand', 'event_partner']
STATUSES = ['active', 'pending', 'suspended', 'deactivated']


# ── Request bodies ───────────────────────────────────────────────────────
class ReasonBody(BaseModel):
    reason: str = ''


class ApproveBody(BaseModel):
    reason: str = ''
    # Social checks only: the follower count the team saw on the profile.
    followers: int | None = None


PLATFORM_NAMES = {'instagram': 'Instagram', 'youtube': 'YouTube', 'x': 'X', 'facebook': 'Facebook', 'linkedin': 'LinkedIn', 'moj': 'Moj'}


class OptionalReason(BaseModel):
    reason: str | None = None


class NoteBody(BaseModel):
    text: str = ''


class EmailBody(BaseModel):
    subject: str = ''
    body: str = ''


class SocialBody(BaseModel):
    platform: str = ''
    handle: str = ''
    followers: int = 0


class StageBody(BaseModel):
    stage: str = ''


class ResolveBody(BaseModel):
    outcome: str = ''
    creatorShare: int = 0
    note: str = ''


class AlertBody(BaseModel):
    brand: str = ''
    creator: str = ''
    evidence: str = ''
    confidence: float | None = None
    windowEnds: str | None = None


class TicketPatch(BaseModel):
    assignee: str | None = None
    status: str | None = None
    priority: str | None = None


class ReplyBody(BaseModel):
    text: str = ''


class InviteBody(BaseModel):
    email: str = ''
    name: str | None = None
    role: str = ''


class RoleBody(BaseModel):
    role: str = ''


# ── Helpers ──────────────────────────────────────────────────────────────
def _reason(value: str | None, what: str = 'reason') -> str:
    text = (value or '').strip()
    if len(text) < 5:
        raise HTTPException(422, f'Give a {what} of at least 5 characters. It is saved in the audit log.')
    return text


def _actor(member: dict) -> str:
    return member.get('name') or member.get('email', 'OPC team')


def _send(bg: BackgroundTasks, to: str | None, subject: str, html: str) -> None:
    if to:
        bg.add_task(email_.send_email_async, to_=to, from_=os.getenv('SMTP_USER'), subject_=subject, body_=html)


def _get_account(person_id: str) -> dict:
    account = col(schema.USERS).find_one({'_id': oid(person_id)})
    if not account:
        raise HTTPException(404, 'Account not found.')
    return account


def _deal_count(account_id: str) -> int:
    return col(schema.DEALS).count_documents({'$or': [{'brandAccountId': account_id}, {'creatorAccountId': account_id}]})


def _person(account: dict) -> dict:
    """USERS doc -> Person."""
    aid = str(account['_id'])
    role = role_of(account)
    profile = account.get('profile') or {}
    if role == 'creator':
        sub = handle_of(account)
    else:
        contact = profile.get('contact', '')
        sub = f"{contact}, {profile['designation']}" if contact and profile.get('designation') else contact
    joined = account.get('joined') or ser(account.get('created_at')) or ''
    person = {
        'id': aid,
        'name': display_name(account),
        'sub': sub or account.get('email', ''),
        'type': role,
        'email': account.get('email', ''),
        'city': profile.get('city', ''),
        'status': status_of(account),
        'verified': bool(account.get('verified', False)),
        'joined': joined,
        'lastActive': account.get('lastActive') or joined,
        'deals': _deal_count(aid),
        'flags': int(account.get('flags', 0)),
        'notes': account.get('notes', []),
    }
    if role == 'creator':
        person['iis'] = int(account.get('iis', 0))
    socials = [
        {'platform': s.get('platform'), 'handle': s.get('handle', ''), 'followers': int(s.get('followers', 0))}
        for s in account.get('socials', []) if s.get('verified')
    ]
    if socials:
        person['socials'] = socials
    return person


def _admin_deal(deal: dict) -> dict:
    """DEALS doc -> AdminDeal. escrow is null while payments are off."""
    return {
        'id': deal.get('code') or str(deal['_id']),
        'campaign': deal.get('campaignName', ''),
        'brand': deal.get('brandName', ''),
        'creator': deal.get('creatorName', ''),
        'budget': deal.get('budget', 0),
        'ris': deal.get('ris', 0),
        'stage': deal.get('stage', 'selected'),
        'escrow': deal.get('escrow') if fees_.PAYMENTS_LIVE else None,
        'updated': deal.get('updatedAt', ''),
    }


def _dispute(doc: dict) -> dict:
    out = {
        'id': doc.get('code') or str(doc['_id']),
        'dealId': doc.get('dealId', ''),
        'campaign': doc.get('campaign', ''),
        'brand': doc.get('brand', ''),
        'creator': doc.get('creator', ''),
        'raisedBy': doc.get('raisedBy', 'brand'),
        'reason': doc.get('reason', ''),
        'held': doc.get('held', 0),
        'opened': doc.get('opened', ''),
        'status': doc.get('status', 'open'),
        'evidence': doc.get('evidence', []),
    }
    if doc.get('outcome'):
        out['outcome'] = doc['outcome']
    return out


def _flag(doc: dict) -> dict:
    return {
        'id': str(doc['_id']),
        'conversation': doc.get('conversation', ''),
        'from': doc.get('from', ''),
        'fromType': doc.get('fromType', 'creator'),
        'message': doc.get('message', ''),
        'reason': doc.get('reason', 'phone'),
        'at': doc.get('at', ''),
        'status': doc.get('status', 'open'),
    }


def _alert(doc: dict) -> dict:
    return {
        'id': str(doc['_id']),
        'brand': doc.get('brand', ''),
        'creator': doc.get('creator', ''),
        'windowEnds': doc.get('windowEnds', ''),
        'detected': doc.get('detected', ''),
        'evidence': doc.get('evidence', ''),
        'confidence': doc.get('confidence', 0.5),
        'status': doc.get('status', 'open'),
    }


def _ticket(doc: dict) -> dict:
    return {
        'id': doc.get('code') or str(doc['_id']),
        'from': doc.get('from', ''),
        'fromType': doc.get('fromType', 'creator'),
        'subject': doc.get('subject', ''),
        'category': doc.get('category', ''),
        'priority': doc.get('priority', 'normal'),
        'status': doc.get('status', 'open'),
        'assignee': doc.get('assignee'),
        'opened': doc.get('opened', ''),
    }


def _member(doc: dict) -> dict:
    out = {
        'id': str(doc['_id']),
        'name': doc.get('name', ''),
        'email': doc.get('email', ''),
        'role': doc.get('role', ''),
        'lastActive': doc.get('lastActive', ''),
    }
    if doc.get('invited'):
        out['invited'] = True
    return out


def _audit_entry(doc: dict) -> dict:
    return {'id': str(doc['_id']), 'actor': doc.get('actor', ''), 'action': doc.get('action', ''),
            'target': doc.get('target', ''), 'at': doc.get('at', '')}


def _newest(docs: list, key: str) -> list:
    return sorted(docs, key=lambda d: (d.get(key) or '', str(d.get('_id'))), reverse=True)


def _names_match(a: str, b: str) -> bool:
    a, b = (a or '').strip().lower(), (b or '').strip().lower()
    return bool(a and b) and (a == b or a.startswith(b) or b.startswith(a))


# ── Who you are and the overview ─────────────────────────────────────────
@router.get('/me')
async def me(member: dict = Depends(staff_member)):
    role = member.get('role', '')
    return {'name': member.get('name', ''), 'email': member.get('email', ''), 'role': role,
            'permissions': ROLE_PERMISSIONS.get(role, [])}


@router.get('/overview')
async def overview(member: dict = Depends(require('people.view'))):
    accounts = [a for a in col(schema.USERS).find() if role_of(a) in MEMBER_ROLES]
    roles = [role_of(a) for a in accounts]
    today = now()
    monday = (today - timedelta(days=today.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    weeks = [monday - timedelta(weeks=i) for i in range(4, -1, -1)]
    joined = []
    for a in accounts:
        stamp = a.get('joined') or ser(a.get('created_at'))
        if stamp:
            try:
                joined.append(parse_iso(stamp))
            except ValueError:
                pass
    signups = []
    for start in weeks:
        end = start + timedelta(weeks=1)
        signups.append({'label': f'{start.day} {start.strftime("%b")}', 'value': sum(1 for j in joined if start <= j < end)})
    recent = _newest(list(col(schema.AUDIT).find()), 'at')[:6]
    return {
        'queues': {
            'verification': col(schema.VERIFICATION).count_documents({}),
            'disputes': col(schema.DISPUTES).count_documents({'status': 'open'}),
            'moderation': col(schema.FLAGS).count_documents({'status': 'open'}) + col(schema.ALERTS).count_documents({'status': 'open'}),
            'payouts': 0,
            'support': sum(1 for t in col(schema.TICKETS).find({'status': {'$ne': 'closed'}}) if not t.get('assignee')),
        },
        'totals': {
            'creators': roles.count('creator'),
            'brands': roles.count('brand'),
            'eventPartners': roles.count('event_partner'),
            'dealsInProgress': col(schema.DEALS).count_documents({'stage': {'$ne': 'paid'}}),
        },
        'signupsByWeek': signups,
        'recent': [_audit_entry(e) for e in recent],
    }


# ── People ───────────────────────────────────────────────────────────────
@router.get('/people')
async def list_people(type: str = Query(''), status: str = Query(''), q: str = Query(''),
                      member: dict = Depends(require('people.view'))):
    people = [_person(a) for a in col(schema.USERS).find() if role_of(a) in MEMBER_ROLES]
    needle = q.strip().lower()
    out = [
        p for p in people
        if (not type or type == 'all' or p['type'] == type)
        and (not status or status == 'all' or p['status'] == status)
        and (not needle or any(needle in str(p[k]).lower() for k in ('name', 'sub', 'email', 'city', 'id')))
    ]
    return sorted(out, key=lambda p: p['lastActive'] or '', reverse=True)


@router.get('/people/{person_id}')
async def get_person(person_id: str, member: dict = Depends(require('people.view'))):
    account = _get_account(person_id)
    person = _person(account)
    deals = col(schema.DEALS).find({'$or': [{'brandAccountId': person_id}, {'creatorAccountId': person_id}]})
    person['deals'] = [_admin_deal(d) for d in _newest(list(deals), 'updatedAt')]
    return person


@router.post('/people/{person_id}/suspend')
async def suspend_person(person_id: str, body: ReasonBody, bg: BackgroundTasks, member: dict = Depends(require('people.suspend'))):
    reason = _reason(body.reason)
    account = _get_account(person_id)
    col(schema.USERS).update_one({'_id': account['_id']}, {'$set': {'status': 'suspended'}})
    _send(bg, account.get('email'), 'Your OPC account is suspended',
          f'<p>Your OPC account has been suspended.</p><p>Reason: {reason}</p>'
          '<p>Deals in progress are paused. Reply to support@theowncollab.com if you think this is a mistake.</p>')
    audit(_actor(member), 'Suspended account', f'{display_name(account)}: {reason}')
    return _person(_get_account(person_id))


@router.post('/people/{person_id}/reactivate')
async def reactivate_person(person_id: str, body: ReasonBody, member: dict = Depends(require('people.suspend'))):
    reason = _reason(body.reason)
    account = _get_account(person_id)
    col(schema.USERS).update_one({'_id': account['_id']}, {'$set': {'status': 'active'}})
    notify(person_id, 'Your account is active again.')
    audit(_actor(member), 'Reactivated account', f'{display_name(account)}: {reason}')
    return _person(_get_account(person_id))


@router.post('/people/{person_id}/notes')
async def add_note(person_id: str, body: NoteBody, member: dict = Depends(require('people.edit'))):
    text = (body.text or '').strip()
    if not text:
        raise HTTPException(422, 'Write the note first.')
    account = _get_account(person_id)
    note = {'by': f"{_actor(member)} ({member.get('role', '')})", 'at': iso(), 'text': text}
    col(schema.USERS).update_one({'_id': account['_id']}, {'$push': {'notes': {'$each': [note], '$position': 0}}})
    audit(_actor(member), 'Added note', display_name(account))
    return _person(_get_account(person_id))


@router.post('/people/{person_id}/email')
async def email_person(person_id: str, body: EmailBody, bg: BackgroundTasks, member: dict = Depends(require('people.edit'))):
    if not body.subject.strip() or not body.body.strip():
        raise HTTPException(422, 'Add a subject and a message.')
    account = _get_account(person_id)
    _send(bg, account.get('email'), body.subject.strip(), body.body.strip().replace('\n', '<br>'))
    audit(_actor(member), 'Sent email', f'{display_name(account)}: {body.subject.strip()}')
    return {'sent': True}


@router.patch('/people/{person_id}/socials')
async def record_social_check(person_id: str, body: SocialBody, member: dict = Depends(require('verification.decide'))):
    platform = (body.platform or '').strip().lower()
    if not platform or not body.handle.strip():
        raise HTTPException(422, 'Give the platform and the handle you checked.')
    if body.followers < 0:
        raise HTTPException(422, 'Followers can’t be negative.')
    account = _get_account(person_id)
    socials = [s for s in account.get('socials', []) if s.get('platform') != platform]
    socials.append({'platform': platform, 'handle': body.handle.strip(), 'followers': body.followers,
                    'verified': True, 'verifiedOn': iso()[:10], 'pending': False})
    col(schema.USERS).update_one({'_id': account['_id']}, {'$set': {'socials': socials}})
    col(schema.VERIFICATION).delete_many({'personId': person_id, 'kind': 'social', 'platform': platform})
    audit(_actor(member), 'Recorded account check', f'{display_name(account)}: {platform} {body.handle.strip()}, {body.followers} followers')
    return _person(_get_account(person_id))


# ── Verification ─────────────────────────────────────────────────────────
def _get_request(request_id: str) -> dict:
    doc = col(schema.VERIFICATION).find_one({'_id': oid(request_id)})
    if not doc:
        raise HTTPException(404, 'This verification request no longer exists.')
    return doc


def _request_out(doc: dict) -> dict:
    out = {'id': str(doc['_id']), 'personId': doc.get('personId', ''), 'name': doc.get('name', ''),
           'type': doc.get('type', 'creator'), 'submitted': doc.get('submitted', ''), 'checks': doc.get('checks', []),
           'kind': doc.get('kind', 'account')}
    if doc.get('platform'):
        out['platform'] = doc['platform']
        out['handle'] = doc.get('handle', '')
    if doc.get('method') == 'dm-code':
        # Instagram / Facebook: has the team sent a code yet, and is it still valid?
        out['method'] = 'dm-code'
        expires = doc.get('codeExpiresAt')
        out['codeStatus'] = 'requested' if not expires else ('sent' if parse_iso(expires) > now() else 'expired')
        if expires:
            out['codeExpiresAt'] = expires
            out['codeSentBy'] = doc.get('codeSentBy', '')
    return out


@router.get('/verification')
async def list_verification(member: dict = Depends(require('verification.decide'))):
    docs = sorted(col(schema.VERIFICATION).find(), key=lambda d: d.get('submitted') or '')
    return [_request_out(d) for d in docs]


@router.post('/verification/{request_id}/approve')
async def approve_verification(request_id: str, body: ApproveBody, member: dict = Depends(require('verification.decide'))):
    reason = _reason(body.reason)
    req = _get_request(request_id)
    account = _get_account(req.get('personId', ''))
    if req.get('kind') == 'social':
        socials = account.get('socials', [])
        for s in socials:
            if s.get('platform') == req.get('platform'):
                s.update({'verified': True, 'pending': False, 'verifiedOn': iso()[:10]})
                if body.followers is not None:
                    if body.followers < 0:
                        raise HTTPException(422, 'Follower count can’t be negative.')
                    s['followers'] = body.followers
                if req.get('handle') and not s.get('handle'):
                    s['handle'] = req['handle']
        col(schema.USERS).update_one({'_id': account['_id']}, {'$set': {'socials': socials}})
        platform = PLATFORM_NAMES.get(req.get('platform', ''), req.get('platform', ''))
        notify(req['personId'], f'Your {platform} account is verified.')
        target = f"{req.get('name', '')} {req.get('platform', '')}: {reason}"
    else:
        col(schema.USERS).update_one({'_id': account['_id']}, {'$set': {'status': 'active', 'verified': True}})
        notify(req['personId'], 'Your account is verified. You can start deals.')
        target = f"{req.get('name', '')}: {reason}"
    col(schema.VERIFICATION).delete_one({'_id': req['_id']})
    audit(_actor(member), 'Approved verification', target)
    return {'ok': True}


@router.post('/verification/{request_id}/reject')
async def reject_verification(request_id: str, body: ReasonBody, bg: BackgroundTasks, member: dict = Depends(require('verification.decide'))):
    reason = _reason(body.reason)
    req = _get_request(request_id)
    account = _get_account(req.get('personId', ''))
    if req.get('kind') == 'social':
        socials = [s for s in account.get('socials', []) if not (s.get('platform') == req.get('platform') and s.get('pending'))]
        col(schema.USERS).update_one({'_id': account['_id']}, {'$set': {'socials': socials}})
        what = f"your {req.get('platform', '')} account"
    else:
        col(schema.USERS).update_one({'_id': account['_id']}, {'$set': {'status': 'deactivated', 'verified': False}})
        what = 'your OPC account'
    col(schema.VERIFICATION).delete_one({'_id': req['_id']})
    _send(bg, account.get('email'), 'Your OPC verification',
          f'<p>We couldn’t verify {what}.</p><p>Reason: {reason}</p><p>You can reply to support@theowncollab.com to appeal.</p>')
    audit(_actor(member), 'Rejected verification', f"{req.get('name', '')}: {reason}")
    return {'ok': True}


@router.post('/verification/{request_id}/request-info')
async def request_info(request_id: str, body: ReasonBody, bg: BackgroundTasks, member: dict = Depends(require('verification.decide'))):
    reason = _reason(body.reason, 'message')
    req = _get_request(request_id)
    account = _get_account(req.get('personId', ''))
    _send(bg, account.get('email'), 'OPC needs a little more information',
          f'<p>To finish verifying your account we need:</p><p>{reason}</p><p>Reply to this email or to support@theowncollab.com.</p>')
    audit(_actor(member), 'Asked for more information', f"{req.get('name', '')}: {reason}")
    return {'ok': True}


# ── Deals ────────────────────────────────────────────────────────────────
def _get_deal(code: str) -> dict:
    deal = col(schema.DEALS).find_one({'code': code}) or col(schema.DEALS).find_one({'_id': oid(code)})
    if not deal:
        raise HTTPException(404, 'Deal not found.')
    return deal


@router.get('/deals')
async def list_deals(member: dict = Depends(require('deals.view'))):
    return [_admin_deal(d) for d in _newest(list(col(schema.DEALS).find()), 'updatedAt')]


@router.post('/deals/{code}/stage')
async def change_stage(code: str, body: StageBody, member: dict = Depends(require('deals.manage'))):
    if body.stage not in DEAL_STAGES:
        raise HTTPException(422, f"Stage must be one of: {', '.join(DEAL_STAGES)}.")
    deal = _get_deal(code)
    update = {'stage': body.stage, 'updatedAt': iso()}
    if body.stage == 'signed' and not deal.get('signedOn'):
        update['signedOn'] = iso()[:10]
    col(schema.DEALS).update_one({'_id': deal['_id']}, {'$set': update})
    for party in (deal.get('brandAccountId'), deal.get('creatorAccountId')):
        if party:
            notify(party, f"{deal.get('campaignName', 'Your deal')} moved to the next stage.")
    audit(_actor(member), 'Moved deal stage', f"{deal.get('code', code)} {deal.get('stage')} → {body.stage}")
    return _admin_deal(_get_deal(code))


# ── Disputes ─────────────────────────────────────────────────────────────
@router.get('/disputes')
async def list_disputes(member: dict = Depends(require('disputes.resolve'))):
    docs = list(col(schema.DISPUTES).find())
    open_first = sorted(docs, key=lambda d: (d.get('status') != 'open', ''.join(chr(255 - ord(c)) for c in (d.get('opened') or ''))))
    return [_dispute(d) for d in open_first]


@router.post('/disputes/{code}/resolve')
async def resolve_dispute(code: str, body: ResolveBody, member: dict = Depends(require('disputes.resolve'))):
    if body.outcome not in ('release', 'refund', 'split'):
        raise HTTPException(422, 'Choose release, refund or split.')
    if not 0 <= body.creatorShare <= 100:
        raise HTTPException(422, 'The creator’s share must be between 0 and 100.')
    note = (body.note or '').strip()
    if len(note) < 10:
        raise HTTPException(422, 'Write a decision note of at least 10 characters. Both sides see it.')
    doc = col(schema.DISPUTES).find_one({'code': code}) or col(schema.DISPUTES).find_one({'_id': oid(code)})
    if not doc:
        raise HTTPException(404, 'Dispute not found.')
    if doc.get('status') == 'resolved':
        raise HTTPException(409, 'This dispute is already resolved.')
    if body.outcome == 'release':
        outcome = 'Held amount released to the creator'
    elif body.outcome == 'refund':
        outcome = 'Held amount refunded to the brand'
    else:
        outcome = f'Split: {body.creatorShare}% to the creator, {100 - body.creatorShare}% to the brand'
    col(schema.DISPUTES).update_one({'_id': doc['_id']}, {'$set': {
        'status': 'resolved', 'outcome': outcome, 'note': note, 'resolvedBy': _actor(member),
        'resolvedAt': iso(), 'creatorShare': body.creatorShare if body.outcome == 'split' else (100 if body.outcome == 'release' else 0),
    }})
    deal = col(schema.DEALS).find_one({'code': doc.get('dealId')})
    parties = {doc.get('raisedByAccountId')}
    if deal:
        parties |= {deal.get('brandAccountId'), deal.get('creatorAccountId')}
    for party in parties - {None}:
        notify(party, f"Dispute {doc.get('code', code)} on {doc.get('campaign', 'your deal')} is resolved. {outcome}.")
    audit(_actor(member), 'Resolved dispute', f"{doc.get('code', code)} {doc.get('campaign', '')}: {outcome}. {note}")
    return _dispute(col(schema.DISPUTES).find_one({'_id': doc['_id']}))


# ── Payouts ──────────────────────────────────────────────────────────────
@router.get('/payouts')
async def list_payouts(member: dict = Depends(require('payouts.release'))):
    """No payouts exist while online payments are off (fees_.PAYMENTS_LIVE)."""
    return []


# ── Moderation: flagged chats ────────────────────────────────────────────
def _get_flag(flag_id: str) -> dict:
    doc = col(schema.FLAGS).find_one({'_id': oid(flag_id)})
    if not doc:
        raise HTTPException(404, 'Flag not found.')
    if doc.get('status') != 'open':
        raise HTTPException(409, 'This flag was already handled.')
    return doc


@router.get('/moderation/flags')
async def list_flags(member: dict = Depends(require('moderation.act'))):
    docs = _newest(list(col(schema.FLAGS).find()), 'at')
    return [_flag(d) for d in sorted(docs, key=lambda d: d.get('status') != 'open')]


@router.post('/moderation/flags/{flag_id}/dismiss')
async def dismiss_flag(flag_id: str, body: OptionalReason, member: dict = Depends(require('moderation.act'))):
    doc = _get_flag(flag_id)
    col(schema.FLAGS).update_one({'_id': doc['_id']}, {'$set': {'status': 'dismissed'}})
    if doc.get('conversationId'):
        col(schema.CONVERSATIONS).update_one({'_id': oid(doc['conversationId'])}, {'$set': {'suspended': False}})
    reason = (body.reason or '').strip()
    audit(_actor(member), 'Dismissed flag and restored chat', f"{doc.get('conversation', '')}{': ' + reason if reason else ''}")
    return _flag(col(schema.FLAGS).find_one({'_id': doc['_id']}))


@router.post('/moderation/flags/{flag_id}/warn')
async def warn_sender(flag_id: str, body: ReasonBody, bg: BackgroundTasks, member: dict = Depends(require('moderation.act'))):
    reason = _reason(body.reason)
    doc = _get_flag(flag_id)
    col(schema.FLAGS).update_one({'_id': doc['_id']}, {'$set': {'status': 'warned'}})
    sender = col(schema.USERS).find_one({'_id': oid(doc.get('fromAccountId', ''))}) if doc.get('fromAccountId') else None
    _send(bg, sender.get('email') if sender else None, 'A warning about your OPC chat',
          f'<p>A message you sent on OPC broke the chat rules.</p><p>{reason}</p>'
          '<p>Keep all contact and payments on OPC. Repeated cases lead to suspension.</p>')
    audit(_actor(member), 'Warned sender', f"{doc.get('from', '')}: {reason}")
    return _flag(col(schema.FLAGS).find_one({'_id': doc['_id']}))


@router.post('/moderation/flags/{flag_id}/suspend')
async def suspend_sender(flag_id: str, body: ReasonBody, bg: BackgroundTasks, member: dict = Depends(require('moderation.act'))):
    reason = _reason(body.reason)
    doc = _get_flag(flag_id)
    col(schema.FLAGS).update_one({'_id': doc['_id']}, {'$set': {'status': 'suspended'}})
    sender = col(schema.USERS).find_one({'_id': oid(doc.get('fromAccountId', ''))}) if doc.get('fromAccountId') else None
    if sender:
        col(schema.USERS).update_one({'_id': sender['_id']}, {'$set': {'status': 'suspended'}})
        _send(bg, sender.get('email'), 'Your OPC account is suspended',
              f'<p>Your OPC account has been suspended after a chat message broke the rules.</p><p>Reason: {reason}</p>')
    audit(_actor(member), 'Suspended account', f"{doc.get('from', '')} (flagged chat): {reason}")
    return _flag(col(schema.FLAGS).find_one({'_id': doc['_id']}))


# ── Moderation: off-platform alerts ──────────────────────────────────────
def _get_alert(alert_id: str) -> dict:
    doc = col(schema.ALERTS).find_one({'_id': oid(alert_id)})
    if not doc:
        raise HTTPException(404, 'Alert not found.')
    if doc.get('status') in ('false-positive', 'penalised'):
        raise HTTPException(409, 'This alert is already closed.')
    return doc


@router.get('/alerts')
async def list_alerts(member: dict = Depends(require('moderation.act'))):
    docs = _newest(list(col(schema.ALERTS).find()), 'detected')
    return [_alert(d) for d in sorted(docs, key=lambda d: d.get('status') not in ('open', 'investigating'))]


@router.post('/alerts')
async def report_alert(body: AlertBody, member: dict = Depends(require('moderation.act'))):
    if not body.brand.strip() or not body.creator.strip():
        raise HTTPException(422, 'Name both the brand and the creator.')
    if len(body.evidence.strip()) < 10:
        raise HTTPException(422, 'Describe the evidence in at least 10 characters, for example a link to the post.')
    confidence = 0.5 if body.confidence is None else body.confidence
    if not 0 <= confidence <= 1:
        raise HTTPException(422, 'Confidence must be between 0 and 1.')
    window = body.windowEnds or ''
    if not window:
        reveal = next((r for r in col(schema.REVEALS).find()
                       if _names_match(r.get('brandName', ''), body.brand) and _names_match(r.get('creatorName', ''), body.creator)), None)
        window = (reveal or {}).get('until', '')
    doc = {'brand': body.brand.strip(), 'creator': body.creator.strip(), 'windowEnds': window, 'detected': iso(),
           'evidence': body.evidence.strip(), 'confidence': confidence, 'status': 'open', 'reportedBy': _actor(member)}
    doc['_id'] = col(schema.ALERTS).insert_one(doc).inserted_id
    audit(_actor(member), 'Reported off-platform alert', f"{doc['brand']} and {doc['creator']}")
    return _alert(doc)


def _set_alert(alert_id: str, status: str, action: str, reason: str, member: dict) -> dict:
    doc = _get_alert(alert_id)
    col(schema.ALERTS).update_one({'_id': doc['_id']}, {'$set': {'status': status}})
    audit(_actor(member), action, f"{doc.get('brand', '')} and {doc.get('creator', '')}: {reason}")
    return doc


@router.post('/alerts/{alert_id}/false-positive')
async def alert_false_positive(alert_id: str, body: ReasonBody, member: dict = Depends(require('moderation.act'))):
    doc = _set_alert(alert_id, 'false-positive', 'Marked alert as false positive', _reason(body.reason), member)
    return _alert(col(schema.ALERTS).find_one({'_id': doc['_id']}))


@router.post('/alerts/{alert_id}/investigate')
async def alert_investigate(alert_id: str, body: ReasonBody, member: dict = Depends(require('moderation.act'))):
    doc = _set_alert(alert_id, 'investigating', 'Opened investigation', _reason(body.reason), member)
    return _alert(col(schema.ALERTS).find_one({'_id': doc['_id']}))


@router.post('/alerts/{alert_id}/penalise')
async def alert_penalise(alert_id: str, body: ReasonBody, bg: BackgroundTasks, member: dict = Depends(require('moderation.act'))):
    reason = _reason(body.reason)
    doc = _set_alert(alert_id, 'penalised', 'Applied off-platform penalty', reason, member)
    for account in col(schema.USERS).find():
        name = display_name(account)
        role = role_of(account)
        hit = (role == 'brand' and _names_match(name, doc.get('brand', ''))) or \
              (role == 'creator' and _names_match(name, doc.get('creator', '')))
        if hit:
            col(schema.USERS).update_one({'_id': account['_id']}, {'$set': {'status': 'suspended'}})
            _send(bg, account.get('email'), 'Your OPC account is suspended',
                  '<p>Your OPC account has been suspended for collaborating outside OPC during the 6-month protection window.</p>'
                  f'<p>Reason: {reason}</p>')
    return _alert(col(schema.ALERTS).find_one({'_id': doc['_id']}))


# ── Support tickets ──────────────────────────────────────────────────────
def _get_ticket(code: str) -> dict:
    doc = col(schema.TICKETS).find_one({'code': code}) or col(schema.TICKETS).find_one({'_id': oid(code)})
    if not doc:
        raise HTTPException(404, 'Ticket not found.')
    return doc


@router.get('/tickets')
async def list_tickets(member: dict = Depends(require('support.reply'))):
    return [_ticket(d) for d in _newest(list(col(schema.TICKETS).find()), 'opened')]


@router.patch('/tickets/{code}')
async def update_ticket(code: str, body: TicketPatch, member: dict = Depends(require('support.reply'))):
    doc = _get_ticket(code)
    changes, said = {}, []
    if 'assignee' in body.model_fields_set:
        assignee = (body.assignee or '').strip() or None
        if assignee and not col(schema.TEAM).find_one({'name': assignee}):
            raise HTTPException(422, f'{assignee} isn’t on the OPC team.')
        changes['assignee'] = assignee
        said.append(f"assigned to {assignee or 'nobody'}")
    if body.status is not None:
        if body.status not in ('open', 'waiting', 'closed'):
            raise HTTPException(422, 'Status must be open, waiting or closed.')
        changes['status'] = body.status
        said.append(f'status {body.status}')
    if body.priority is not None:
        if body.priority not in ('low', 'normal', 'high'):
            raise HTTPException(422, 'Priority must be low, normal or high.')
        changes['priority'] = body.priority
        said.append(f'priority {body.priority}')
    if not changes:
        raise HTTPException(422, 'Nothing to change.')
    col(schema.TICKETS).update_one({'_id': doc['_id']}, {'$set': changes})
    audit(_actor(member), 'Updated ticket', f"{doc.get('code', code)}: {', '.join(said)}")
    return _ticket(_get_ticket(code))


@router.post('/tickets/{code}/reply')
async def reply_ticket(code: str, body: ReplyBody, bg: BackgroundTasks, member: dict = Depends(require('support.reply'))):
    text = (body.text or '').strip()
    if not text:
        raise HTTPException(422, 'Write your reply first.')
    doc = _get_ticket(code)
    reply = {'by': _actor(member), 'text': text, 'at': iso()}
    col(schema.TICKETS).update_one({'_id': doc['_id']}, {'$push': {'replies': reply}, '$set': {'status': 'waiting'}})
    account = col(schema.USERS).find_one({'_id': oid(doc.get('accountId', ''))}) if doc.get('accountId') else None
    if account:
        _send(bg, account.get('email'), f"Re: {doc.get('subject', 'your OPC ticket')} [{doc.get('code', code)}]",
              text.replace('\n', '<br>') + '<p>The OPC team</p>')
        notify(doc['accountId'], f"OPC replied to ticket {doc.get('code', code)}.")
    audit(_actor(member), 'Replied to ticket', doc.get('code', code))
    return _ticket(_get_ticket(code))


# ── Team ─────────────────────────────────────────────────────────────────
EMAIL_RE = re.compile(r'^[^\s@]+@theowncollab\.com$', re.IGNORECASE)


def _get_member(member_id: str) -> dict:
    doc = col(schema.TEAM).find_one({'_id': oid(member_id)})
    if not doc:
        raise HTTPException(404, 'Team member not found.')
    return doc


@router.get('/team')
async def list_team(member: dict = Depends(staff_member)):
    order = {r: i for i, r in enumerate(TEAM_ROLES)}
    docs = sorted(col(schema.TEAM).find(), key=lambda d: (order.get(d.get('role'), 99), d.get('name', '')))
    return [_member(d) for d in docs]


@router.post('/team/invite')
async def invite_member(body: InviteBody, bg: BackgroundTasks, member: dict = Depends(require('team.manage'))):
    email = (body.email or '').strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(422, 'Only @theowncollab.com addresses can join the team.')
    if body.role not in TEAM_ROLES:
        raise HTTPException(422, f"Role must be one of: {', '.join(TEAM_ROLES)}.")
    if body.role == 'Owner':
        raise HTTPException(422, 'Invites can’t create another Owner.')
    if col(schema.TEAM).find_one({'email': email}):
        raise HTTPException(409, f'{email} is already on the team.')
    doc = {'email': email, 'name': (body.name or '').strip() or email.split('@')[0].replace('.', ' ').title(),
           'role': body.role, 'lastActive': '', 'invited': True}
    doc['_id'] = col(schema.TEAM).insert_one(doc).inserted_id
    _send(bg, email, 'You’re invited to the OPC team console',
          f'<p>{_actor(member)} added you to the OPC team as {body.role}.</p>'
          '<p>Sign in on theowncollab.com with this Google account, then open the team console from your dashboard.</p>')
    audit(_actor(member), 'Invited team member', f'{email} as {body.role}')
    return _member(doc)


@router.patch('/team/{member_id}')
async def change_role(member_id: str, body: RoleBody, member: dict = Depends(require('team.manage'))):
    target = _get_member(member_id)
    if body.role not in TEAM_ROLES:
        raise HTTPException(422, f"Role must be one of: {', '.join(TEAM_ROLES)}.")
    if body.role == 'Owner':
        raise HTTPException(422, 'You can’t make someone an Owner here.')
    if target.get('role') == 'Owner':
        raise HTTPException(403, 'An Owner’s role can’t be changed.')
    if target['_id'] == member['_id']:
        raise HTTPException(403, 'You can’t change your own role.')
    col(schema.TEAM).update_one({'_id': target['_id']}, {'$set': {'role': body.role}})
    audit(_actor(member), 'Changed team role', f"{target.get('name', '')}: {target.get('role')} → {body.role}")
    return _member(_get_member(member_id))


@router.delete('/team/{member_id}')
async def remove_member(member_id: str, member: dict = Depends(require('team.manage'))):
    target = _get_member(member_id)
    if target.get('role') == 'Owner':
        raise HTTPException(403, 'An Owner can’t be removed.')
    if target['_id'] == member['_id']:
        raise HTTPException(403, 'You can’t remove yourself.')
    col(schema.TEAM).delete_one({'_id': target['_id']})
    audit(_actor(member), 'Removed team member', f"{target.get('name', '')} ({target.get('email', '')})")
    return {'ok': True}


# ── Audit log ────────────────────────────────────────────────────────────
@router.get('/audit')
async def audit_log(q: str = Query(''), actor: str = Query(''), format: str = Query('json'),
                    member: dict = Depends(require('audit.view'))):
    needle = q.strip().lower()
    entries = [
        _audit_entry(e) for e in _newest(list(col(schema.AUDIT).find()), 'at')
        if (not actor or actor == 'all' or e.get('actor') == actor)
        and (not needle or needle in f"{e.get('action', '')} {e.get('target', '')}".lower())
    ]
    if format == 'csv':
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(['When', 'Who', 'Action', 'Details'])
        for e in entries:
            writer.writerow([e['at'], e['actor'], e['action'], e['target']])
        return Response(buf.getvalue(), media_type='text/csv',
                        headers={'Content-Disposition': 'attachment; filename="opc-audit-log.csv"'})
    return entries
