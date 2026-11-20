"""
Instagram and Facebook verification without platform sign-in.

1. DM codes
   - The creator (or brand) submits their Instagram handle or Facebook ID.
   - The team sees it in the console, generates a 6-digit code and sends it by DM
     from OPC's own Instagram / Facebook account.
   - The person types the code into their dashboard. A code works for 12 hours,
     with 5 tries. Only a hash of the code is stored.

2. Instagram invite links
   - The team creates a single-use link for one Instagram handle. It works for 7 days.
   - Whoever signs up through it gets that Instagram account verified automatically.
   - The link is shown once when it's made; only a hash of its token is stored.
"""
import hashlib
import re
import secrets
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from database import schema
from utils.deps_ import creator_account, creator_or_brand, require
from utils.helpers_ import audit, col, display_name, iso, iso_in, now, oid, parse_iso, role_of

router = APIRouter()

CODE_HOURS = 12
CODE_ATTEMPTS = 5
INVITE_DAYS = 7
DM_PLATFORMS = ('instagram', 'facebook')
PLATFORM_NAMES = {'instagram': 'Instagram', 'facebook': 'Facebook'}
INSTAGRAM_HANDLE = re.compile(r'^[A-Za-z0-9._]{1,30}$')


def _hash(value: str, salt: str = '') -> str:
    return hashlib.sha256(f'{salt}:{value}'.encode()).hexdigest()


def normalise_handle(platform: str, raw: str) -> str:
    """Instagram: '@name' (from a handle or profile link). Facebook: the ID, username or profile link as given."""
    value = raw.strip()
    if platform == 'instagram':
        value = re.sub(r'^(https?://)?(www\.)?instagram\.com/', '', value).strip('/').split('?')[0].lstrip('@')
        if not INSTAGRAM_HANDLE.match(value):
            raise HTTPException(422, 'Enter your Instagram handle, like @yourname (letters, numbers, dots and underscores).')
        return f'@{value.lower()}'
    if not value or len(value) > 100:
        raise HTTPException(422, 'Enter your Facebook profile link, username or ID.')
    return value


def code_status(social: dict) -> Optional[str]:
    """For a pending Instagram/Facebook check: requested (no code yet), sent (code valid) or expired."""
    if not social.get('pending') or social.get('platform') not in DM_PLATFORMS:
        return None
    expires = social.get('codeExpiresAt')
    if not expires:
        return 'requested'
    return 'sent' if parse_iso(expires) > now() else 'expired'


def _replace_social(account: dict, entry: dict) -> list:
    socials = [s for s in (account.get('socials') or []) if s.get('platform') != entry['platform']]
    socials.append(entry)
    col(schema.USERS).update_one({'_id': account['_id']}, {'$set': {'socials': socials}})
    return socials


def _socials_out(account_id) -> list:
    """Same shape as GET /api/users/me socials, plus the code status for pending DM checks."""
    account = col(schema.USERS).find_one({'_id': account_id})
    out = []
    for s in account.get('socials') or []:
        item = {'platform': s.get('platform'), 'handle': s.get('handle', ''), 'followers': int(s.get('followers') or 0), 'verified': bool(s.get('verified'))}
        for key in ('verifiedOn', 'via', 'codeExpiresAt'):
            if s.get(key):
                item[key] = s[key]
        if s.get('pending'):
            item['pending'] = True
            item['codeStatus'] = code_status(s)
        out.append(item)
    return out


# ── 1. DM codes: the person's side ──────────────────────────────────────
class RequestCodeBody(BaseModel):
    platform: Literal['instagram', 'facebook']
    handle: str = Field(min_length=1, max_length=120)


class ConfirmCodeBody(BaseModel):
    platform: Literal['instagram', 'facebook']
    code: str = Field(min_length=6, max_length=6)


@router.post('/api/users/me/socials/request-code')
async def request_code(body: RequestCodeBody, account: dict = Depends(creator_or_brand)):
    """Ask OPC to DM a verification code to this Instagram handle or Facebook ID."""
    handle = normalise_handle(body.platform, body.handle)
    _replace_social(account, {'platform': body.platform, 'handle': handle, 'followers': 0, 'verified': False, 'pending': True})
    person_id = str(account['_id'])
    col(schema.VERIFICATION).delete_many({'personId': person_id, 'kind': 'social', 'platform': body.platform})
    col(schema.VERIFICATION).insert_one({
        'personId': person_id,
        'name': display_name(account),
        'type': role_of(account),
        'kind': 'social',
        'method': 'dm-code',
        'platform': body.platform,
        'handle': handle,
        'submitted': iso(),
        'checks': [{'label': f'{PLATFORM_NAMES[body.platform]} account {handle}', 'ok': None,
                    'detail': f'Send a code by DM from OPC’s {PLATFORM_NAMES[body.platform]} account'}],
    })
    return {'socials': _socials_out(account['_id'])}


@router.post('/api/users/me/socials/confirm-code')
async def confirm_code(body: ConfirmCodeBody, account: dict = Depends(creator_or_brand)):
    """Check the code OPC sent by DM. Right code within 12 hours: the account is verified."""
    person_id = str(account['_id'])
    req = col(schema.VERIFICATION).find_one({'personId': person_id, 'kind': 'social', 'platform': body.platform})
    if not req or not req.get('code_hash'):
        raise HTTPException(409, 'OPC hasn’t sent you a code yet. You’ll get a DM soon after you ask for one.')
    if parse_iso(req['codeExpiresAt']) <= now():
        raise HTTPException(410, 'This code has expired. Ask for a new one.')
    if req.get('attempts', 0) >= CODE_ATTEMPTS:
        raise HTTPException(429, 'Too many wrong tries. Ask for a new code.')
    if _hash(body.code.strip(), str(req['_id'])) != req['code_hash']:
        col(schema.VERIFICATION).update_one({'_id': req['_id']}, {'$inc': {'attempts': 1}})
        left = CODE_ATTEMPTS - req.get('attempts', 0) - 1
        raise HTTPException(400, f'That code isn’t right. Check the DM from OPC and try again ({left} tries left).')

    _replace_social(account, {'platform': body.platform, 'handle': req['handle'], 'followers': int(req.get('followers') or 0),
                              'verified': True, 'pending': False, 'verifiedOn': iso()[:10], 'via': 'dm-code'})
    col(schema.VERIFICATION).delete_one({'_id': req['_id']})
    audit('System', 'Verified account by DM code', f"{display_name(account)}: {PLATFORM_NAMES[body.platform]} {req['handle']}")
    return {'socials': _socials_out(account['_id'])}


# ── 1. DM codes: the team's side ────────────────────────────────────────
class GenerateCodeBody(BaseModel):
    followers: Optional[int] = Field(default=None, ge=0)


@router.post('/api/admin/verification/{request_id}/code')
async def generate_code(request_id: str, body: GenerateCodeBody, member: dict = Depends(require('verification.decide'))):
    """Make a 6-digit code for the team to DM. Shown once; valid for 12 hours. Making a new one replaces the old one."""
    req = col(schema.VERIFICATION).find_one({'_id': oid(request_id)})
    if not req:
        raise HTTPException(404, 'This verification request no longer exists.')
    if req.get('kind') != 'social' or req.get('platform') not in DM_PLATFORMS:
        raise HTTPException(409, 'Codes are only for Instagram and Facebook checks.')
    code = f'{secrets.randbelow(10 ** 6):06d}'
    expires = iso_in(minutes=CODE_HOURS * 60)
    update = {'code_hash': _hash(code, str(req['_id'])), 'codeExpiresAt': expires, 'codeSentBy': member.get('name', ''), 'attempts': 0}
    if body.followers is not None:
        update['followers'] = body.followers
    col(schema.VERIFICATION).update_one({'_id': req['_id']}, {'$set': update})

    account = col(schema.USERS).find_one({'_id': oid(req['personId'])})
    if account:
        socials = account.get('socials') or []
        for s in socials:
            if s.get('platform') == req['platform']:
                s['codeExpiresAt'] = expires
        col(schema.USERS).update_one({'_id': account['_id']}, {'$set': {'socials': socials}})
    platform = PLATFORM_NAMES[req['platform']]
    audit(member.get('name', 'Team'), 'Generated verification code', f"{req.get('name', '')}: {platform} {req.get('handle', '')}")
    message = (f'Hi! Your OPC verification code is {code}. Enter it on your OPC dashboard under "Verify accounts" '
               f'within {CODE_HOURS} hours. Never share this code with anyone else.')
    return {'code': code, 'expiresAt': expires, 'message': message, 'platform': req['platform'], 'handle': req.get('handle', '')}


# ── 2. Instagram invite links ───────────────────────────────────────────
def invite_status(doc: dict) -> str:
    if doc.get('revokedAt'):
        return 'revoked'
    if doc.get('usedAt'):
        return 'used'
    if parse_iso(doc['expiresAt']) <= now():
        return 'expired'
    return 'active'


def _invite_out(doc: dict) -> dict:
    return {
        'id': str(doc['_id']),
        'platform': 'instagram',
        'handle': doc['handle'],
        'name': doc.get('name') or '',
        'followers': int(doc.get('followers') or 0),
        'note': doc.get('note') or '',
        'createdBy': doc.get('createdBy', ''),
        'createdAt': doc['createdAt'],
        'expiresAt': doc['expiresAt'],
        'status': invite_status(doc),
        'usedBy': doc.get('usedByName') or None,
        'usedAt': doc.get('usedAt') or None,
    }


class InviteBody(BaseModel):
    handle: str = Field(min_length=1, max_length=120)
    name: Optional[str] = Field(default=None, max_length=120)
    followers: Optional[int] = Field(default=None, ge=0)
    note: Optional[str] = Field(default=None, max_length=500)


class RevokeBody(BaseModel):
    reason: str = ''


@router.post('/api/admin/invites')
async def create_invite(body: InviteBody, member: dict = Depends(require('verification.decide'))):
    """A single-use sign-up link that verifies one Instagram handle. Valid for 7 days. The token is returned once."""
    handle = normalise_handle('instagram', body.handle)
    token = secrets.token_urlsafe(24)
    doc = {
        'token_hash': _hash(token),
        'platform': 'instagram',
        'handle': handle,
        'name': (body.name or '').strip(),
        'followers': body.followers or 0,
        'note': (body.note or '').strip(),
        'createdBy': member.get('name', ''),
        'createdAt': iso(),
        'expiresAt': iso_in(days=INVITE_DAYS),
    }
    doc['_id'] = col(schema.INVITES).insert_one(doc).inserted_id
    audit(member.get('name', 'Team'), 'Created Instagram invite', f"{handle}{' for ' + doc['name'] if doc['name'] else ''}")
    return {'invite': _invite_out(doc), 'token': token}


@router.get('/api/admin/invites')
async def list_invites(member: dict = Depends(require('verification.decide'))):
    return [_invite_out(d) for d in col(schema.INVITES).find({}).sort('createdAt', -1)]


@router.post('/api/admin/invites/{invite_id}/revoke')
async def revoke_invite(invite_id: str, body: RevokeBody, member: dict = Depends(require('verification.decide'))):
    reason = (body.reason or '').strip()
    if len(reason) < 5:
        raise HTTPException(422, 'Give a reason of at least 5 characters. It is saved in the audit log.')
    doc = col(schema.INVITES).find_one({'_id': oid(invite_id)})
    if not doc:
        raise HTTPException(404, 'This invite doesn’t exist.')
    if invite_status(doc) != 'active':
        raise HTTPException(409, 'Only an unused, unexpired invite can be revoked.')
    col(schema.INVITES).update_one({'_id': doc['_id']}, {'$set': {'revokedAt': iso()}})
    audit(member.get('name', 'Team'), 'Revoked Instagram invite', f"{doc['handle']}: {reason}")
    return _invite_out(col(schema.INVITES).find_one({'_id': doc['_id']}))


def _find_invite(token: str) -> dict:
    doc = col(schema.INVITES).find_one({'token_hash': _hash(token)})
    if not doc:
        raise HTTPException(404, 'This invite link isn’t valid. Ask OPC for a new one.')
    return doc


@router.get('/api/invites/{token}')
async def view_invite(token: str):
    """Public: what the invite landing page shows before sign-up."""
    doc = _find_invite(token)
    return {'handle': doc['handle'], 'name': doc.get('name') or '', 'expiresAt': doc['expiresAt'], 'status': invite_status(doc)}


def redeem_invite_for_account(token: str, account: dict) -> bool:
    """After sign-up: automatically verify the invite's Instagram handle on this creator account."""
    try:
        doc = _find_invite(token)
        if invite_status(doc) != 'active':
            return False
        taken = col(schema.USERS).find_one({
            '_id': {'$ne': account['_id']},
            'socials': {'$elemMatch': {'platform': 'instagram', 'handle': doc['handle'], 'verified': True}},
        })
        if taken:
            return False
        _replace_social(account, {'platform': 'instagram', 'handle': doc['handle'], 'followers': int(doc.get('followers') or 0),
                                  'verified': True, 'pending': False, 'verifiedOn': iso()[:10], 'via': 'invite'})
        col(schema.VERIFICATION).delete_many({'personId': str(account['_id']), 'kind': 'social', 'platform': 'instagram'})
        col(schema.INVITES).update_one({'_id': doc['_id']}, {'$set': {'usedAt': iso(), 'usedBy': str(account['_id']), 'usedByName': display_name(account)}})
        audit('System', 'Used Instagram invite', f"{display_name(account)}: {doc['handle']}")
        return True
    except Exception as e:
        print(f"[INVITE WARNING] Auto-redeem failed: {e}")
        return False


@router.post('/api/invites/{token}/redeem')
async def redeem_invite(token: str, account: dict = Depends(creator_account)):
    """After sign-up: verify the invite's Instagram handle on this creator account. Single use."""
    doc = _find_invite(token)
    status = invite_status(doc)
    if status != 'active':
        raise HTTPException(410, {
            'used': 'This invite link has already been used.',
            'expired': 'This invite link has expired. Ask OPC for a new one.',
            'revoked': 'This invite link was cancelled. Ask OPC for a new one.',
        }[status])
    taken = col(schema.USERS).find_one({
        '_id': {'$ne': account['_id']},
        'socials': {'$elemMatch': {'platform': 'instagram', 'handle': doc['handle'], 'verified': True}},
    })
    if taken:
        raise HTTPException(409, 'This Instagram account is already verified on another OPC account.')
    _replace_social(account, {'platform': 'instagram', 'handle': doc['handle'], 'followers': int(doc.get('followers') or 0),
                              'verified': True, 'pending': False, 'verifiedOn': iso()[:10], 'via': 'invite'})
    col(schema.VERIFICATION).delete_many({'personId': str(account['_id']), 'kind': 'social', 'platform': 'instagram'})
    col(schema.INVITES).update_one({'_id': doc['_id']}, {'$set': {'usedAt': iso(), 'usedBy': str(account['_id']), 'usedByName': display_name(account)}})
    audit('System', 'Used Instagram invite', f"{display_name(account)}: {doc['handle']}")
    return {'socials': _socials_out(account['_id'])}
