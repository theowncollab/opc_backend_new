"""
Dashboard API, section A: account, onboarding, signature, profile edits (with an
emailed code), closing an account, manual social checks and brand work-email
verification. Contract: DASHBOARD_API.md. Storage: database/schema.py.
"""
import base64
import hashlib
import os
import re
import secrets
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from database import schema
from utils import email_
from utils.deps_ import brand_account, creator_or_brand, current_user
from routes.social_verify import code_status
from utils.helpers_ import col, display_name, iso, iso_in, now, parse_iso, role_of, status_of

router = APIRouter()

FREE_MAIL = {
    'gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'rediffmail.com',
    'icloud.com', 'proton.me', 'live.com', 'ymail.com',
}
PLATFORM_NAMES = {'instagram': 'Instagram', 'youtube': 'YouTube', 'x': 'X', 'facebook': 'Facebook', 'linkedin': 'LinkedIn', 'moj': 'Moj'}
EMAIL_RE = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
MAX_SIGNATURE_BYTES = 200 * 1024
OTP_MINUTES = 10
OTP_MAX_ATTEMPTS = 5
OTP_MAX_PER_DAY = 5

# Onboarding form keys copied into `profile`, per role.
ONBOARDING_KEYS = {
    'creator': ['legalName', 'displayName', 'city', 'niche', 'niche2', 'format', 'audience', 'phone'],
    'brand': ['company', 'industry', 'contact', 'designation', 'city', 'website', 'gstin', 'about', 'signatory', 'phone'],
}
# Profile keys editable after onboarding (needs a fresh emailed code).
EDITABLE_KEYS = {
    'creator': ['legalName', 'displayName', 'city', 'niche', 'phone'],
    'brand': ['company', 'industry', 'website', 'gstin', 'contact', 'designation', 'phone', 'signatory'],
}
REQUIRED_KEYS = {
    'creator': ['legalName', 'displayName', 'city', 'niche'],
    'brand': ['company', 'industry', 'contact', 'city'],
}
FIELD_LABELS = {
    'legalName': 'full legal name', 'displayName': 'creator name', 'city': 'city', 'niche': 'main niche',
    'company': 'company name', 'industry': 'industry', 'contact': 'contact person', 'phone': 'phone number',
}


# ── Shapes returned to the dashboard ─────────────────────────────────────
def _socials(account: dict) -> list:
    out = []
    for s in account.get('socials') or []:
        item = {
            'platform': s.get('platform'),
            'handle': s.get('handle', ''),
            'followers': int(s.get('followers') or 0),
            'verified': bool(s.get('verified')),
        }
        for key in ('verifiedOn', 'via', 'codeExpiresAt'):
            if s.get(key):
                item[key] = s[key]
        if s.get('pending'):
            item['pending'] = True
            item['codeStatus'] = code_status(s)
        out.append(item)
    return out


def profile_of(account: dict) -> dict:
    """CreatorProfile or BrandProfile (dashboard-app/src/data/types.ts) plus status and onboarded."""
    p = account.get('profile') or {}
    common = {
        'id': str(account['_id']),
        'memberSince': account.get('joined') or account.get('createdAt') or now(),
        'status': status_of(account),
        'onboarded': bool((account.get('onboarding') or {}).get('completedAt')),
    }
    if role_of(account) == 'creator':
        factors = account.get('iisFactors') or {}
        return {
            **common,
            'legalName': p.get('legalName', ''),
            'displayName': p.get('displayName', ''),
            'email': account.get('email', ''),
            'phone': p.get('phone', ''),
            'city': p.get('city', ''),
            'niche': p.get('niche', ''),
            'secondaryNiche': p.get('niche2', ''),
            'iis': int(account.get('iis') or 0),
            'iisFactors': {k: float(factors.get(k) or 0) for k in ('engagement', 'quality', 'reliability', 'growth')},
            'engagementRate': float(account.get('engagementRate') or 0),
            'rating': float(account.get('rating') or 0),
            'socials': _socials(account),
            'payout': {},  # payments are off: never ask for or return bank details
            'signatureOnFile': bool(account.get('signature')),
        }
    return {
        **common,
        'companyName': p.get('company', ''),
        'industry': p.get('industry', ''),
        'workEmail': p.get('workEmail', ''),
        'contactName': p.get('contact', ''),
        'designation': p.get('designation', ''),
        'phone': p.get('phone', ''),
        'city': p.get('city', ''),
        'website': p.get('website', ''),
        'gstin': p.get('gstin', ''),
        'verified': bool(account.get('verified')),
        'signatoryName': p.get('signatory', ''),
    }


def _reload(account: dict) -> dict:
    return col(schema.USERS).find_one({'_id': account['_id']})


def _set(account: dict, fields: dict) -> None:
    col(schema.USERS).update_one({'_id': account['_id']}, {'$set': fields})


# ── One-time codes ───────────────────────────────────────────────────────
def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def _issue_code(recipient: str, purpose: str, account_id: str | None, tasks: BackgroundTasks, subject: str, intro: str) -> None:
    """Create a 6-digit code, keep only its hash, and email it. 5 codes a day per recipient and purpose."""
    since = iso_in(days=-1)
    sent_today = col(schema.OTP).count_documents({'email': recipient, 'purpose': purpose, 'created': {'$gte': since}})
    if sent_today >= OTP_MAX_PER_DAY:
        raise HTTPException(429, 'Too many codes today. Try again tomorrow.')
    code = str(secrets.randbelow(10 ** 6)).zfill(6)
    col(schema.OTP).insert_one({
        'email': recipient,
        'purpose': purpose,
        'accountId': account_id,
        'code_hash': _hash(code),
        'expires': iso_in(minutes=OTP_MINUTES),
        'attempts': 0,
        'used': False,
        'created': iso(),
    })
    body = f"<p>{intro}</p><p style='font-size:24px;letter-spacing:4px'><b>{code}</b></p><p>It expires in {OTP_MINUTES} minutes. If you didn’t ask for it, ignore this email.</p>"
    tasks.add_task(email_.send_email_async, to_=recipient, from_=os.getenv('SMTP_USER') or 'opc.owncollab@gmail.com', subject_=subject, body_=body)


def _check_code(query: dict, code: str) -> None:
    """Raise unless `code` matches the newest unused, unexpired code for `query`."""
    docs = list(col(schema.OTP).find({**query, 'used': False}).sort('created', -1).limit(1))
    doc = docs[0] if docs else None
    if not doc or parse_iso(doc['expires']) <= now():
        raise HTTPException(400, 'That code has expired. Ask for a new one.')
    if doc.get('attempts', 0) >= OTP_MAX_ATTEMPTS:
        raise HTTPException(429, 'Too many wrong tries. Ask for a new code.')
    if _hash(code.strip()) != doc['code_hash']:
        col(schema.OTP).update_one({'_id': doc['_id']}, {'$inc': {'attempts': 1}})
        raise HTTPException(400, 'That code isn’t right. Check the email and try again.')
    col(schema.OTP).update_one({'_id': doc['_id']}, {'$set': {'used': True}})


# ── Request bodies ───────────────────────────────────────────────────────
class OnboardingBody(BaseModel):
    step: int = Field(ge=0, le=10)
    data: dict = Field(default_factory=dict)


class SignatureBody(BaseModel):
    mode: Literal['draw', 'type']
    dataUrl: Optional[str] = None
    typed: Optional[str] = None
    consentVersion: str = Field(min_length=1)


class CompleteBody(BaseModel):
    agreementVersion: str = Field(min_length=1)
    checks: list[bool]


class CodeBody(BaseModel):
    code: str = Field(min_length=6, max_length=6)


class ProfileEdit(BaseModel):
    legalName: Optional[str] = None
    displayName: Optional[str] = None
    city: Optional[str] = None
    niche: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    industry: Optional[str] = None
    website: Optional[str] = None
    gstin: Optional[str] = None
    contact: Optional[str] = None
    designation: Optional[str] = None
    signatory: Optional[str] = None


class CloseBody(BaseModel):
    reason: str = Field(min_length=1)
    feedback: Optional[str] = None


class DeleteBody(CloseBody):
    confirm: str


class WorkEmailBody(BaseModel):
    email: str


class ConfirmEmailBody(BaseModel):
    email: str
    code: str = Field(min_length=6, max_length=6)


# ── Profile ──────────────────────────────────────────────────────────────
@router.get('/api/users/me')
async def get_me(account: dict = Depends(creator_or_brand)):
    """The signed-in person's creator or brand profile (`?role=`)."""
    return profile_of(account)


@router.put('/api/users/me')
async def edit_me(body: ProfileEdit, account: dict = Depends(creator_or_brand)):
    """Edit profile details. Needs a code from POST /api/users/me/otp/verify in the last 10 minutes."""
    ok_until = account.get('otp_ok_until')
    if not ok_until or parse_iso(ok_until) <= now():
        raise HTTPException(403, 'Confirm with the code we emailed you first.')
    allowed = EDITABLE_KEYS[role_of(account)]
    changes = {f'profile.{k}': v.strip() for k, v in body.model_dump(exclude_none=True).items() if k in allowed}
    if changes:
        _set(account, changes)
    return profile_of(_reload(account))


@router.post('/api/users/me/otp')
async def send_profile_code(tasks: BackgroundTasks, user: dict = Depends(current_user)):
    """Email a 6-digit code that unlocks profile edits."""
    _issue_code(user['email'], 'profile', None, tasks, 'Your OPC confirmation code', 'Use this code to confirm the change to your OPC profile.')
    return {'sent': True}


@router.post('/api/users/me/otp/verify')
async def verify_profile_code(body: CodeBody, user: dict = Depends(current_user)):
    """Check the emailed code; profile edits are then allowed for 10 minutes on every account of this email."""
    _check_code({'email': user['email'], 'purpose': 'profile'}, body.code)
    col(schema.USERS).update_many({'email': user['email']}, {'$set': {'otp_ok_until': iso_in(minutes=OTP_MINUTES)}})
    return {'ok': True}


# ── Onboarding ───────────────────────────────────────────────────────────
@router.get('/api/users/me/onboarding')
async def get_onboarding(account: dict = Depends(creator_or_brand)):
    ob = account.get('onboarding') or {}
    return {'step': int(ob.get('step') or 0), 'data': ob.get('data') or {}, 'completed': bool(ob.get('completedAt'))}


@router.put('/api/users/me/onboarding')
async def save_onboarding(body: OnboardingBody, account: dict = Depends(creator_or_brand)):
    """Save progress after each step; known keys are copied into the profile."""
    ob = account.get('onboarding') or {}
    data = {**(ob.get('data') or {}), **body.data}
    fields = {'onboarding.step': body.step, 'onboarding.data': data}
    for key in ONBOARDING_KEYS[role_of(account)]:
        value = body.data.get(key)
        if isinstance(value, str):
            fields[f'profile.{key}'] = value.strip()
    _set(account, fields)
    return {'step': body.step}


@router.post('/api/users/me/signature')
async def save_signature(body: SignatureBody, account: dict = Depends(creator_or_brand)):
    """Drawn (PNG) or typed signature, with the consent text version it was given under."""
    signature = {'mode': body.mode, 'consentVersion': body.consentVersion, 'at': iso()}
    if body.mode == 'draw':
        prefix = 'data:image/png;base64,'
        if not body.dataUrl or not body.dataUrl.startswith(prefix):
            raise HTTPException(422, 'Send the drawn signature as a PNG image.')
        try:
            raw = base64.b64decode(body.dataUrl[len(prefix):], validate=True)
        except Exception:
            raise HTTPException(422, 'The signature image couldn’t be read. Draw it again.')
        if len(raw) > MAX_SIGNATURE_BYTES:
            raise HTTPException(422, 'The signature image is too large. It must be under 200 KB.')
        signature['dataUrl'] = body.dataUrl
    else:
        if not body.typed or not body.typed.strip():
            raise HTTPException(422, 'Type your full name to sign.')
        signature['typed'] = body.typed.strip()
    _set(account, {'signature': signature})
    return {'ok': True}


@router.post('/api/users/me/onboarding/complete')
async def complete_onboarding(body: CompleteBody, account: dict = Depends(creator_or_brand)):
    """Activate the account: it then waits in the team's Verification queue."""
    role = role_of(account)
    profile = account.get('profile') or {}
    if not body.checks or not all(body.checks):
        raise HTTPException(422, 'Tick every box to accept the agreement.')
    missing = [FIELD_LABELS[k] for k in REQUIRED_KEYS[role] if not str(profile.get(k) or '').strip()]
    if missing:
        raise HTTPException(422, f"Add your {', '.join(missing)} first.")
    if not account.get('signature'):
        raise HTTPException(422, 'Add your signature first.')
    socials = account.get('socials') or []
    if role == 'creator' and not any(s.get('verified') or s.get('pending') for s in socials):
        raise HTTPException(422, 'Verify at least one social account, or request a manual check, first.')
    if role == 'brand' and not account.get('emailVerified'):
        raise HTTPException(422, 'Verify your work email first.')

    _set(account, {
        'onboarding.completedAt': iso(),
        'onboarding.agreementVersion': body.agreementVersion,
        'onboarding.checks': body.checks,
        'status': 'pending',
        'verified': False,
    })
    if role == 'creator':
        verified = [s for s in socials if s.get('verified')]
        checks = [
            {'label': 'Profile complete', 'ok': True},
            {
                'label': 'Social account verified',
                'ok': True if verified else None,
                'detail': ', '.join(f"{PLATFORM_NAMES.get(s['platform'], s['platform'])} {s.get('handle', '')}".strip() for s in verified)
                or 'Waiting for a manual check',
            },
            {'label': 'Signature added', 'ok': True},
            {'label': 'Agreement accepted', 'ok': True, 'detail': f'Version {body.agreementVersion}'},
        ]
    else:
        checks = [
            {'label': 'Work email confirmed', 'ok': True, 'detail': profile.get('workEmail', '')},
            {'label': 'Email domain matches company', 'ok': None, 'detail': 'Check by hand'},
            {'label': 'GST number valid', 'ok': None, 'detail': 'Check by hand' if profile.get('gstin') else 'Not provided yet'},
            {'label': 'Signatory and signature added', 'ok': True},
        ]
    col(schema.VERIFICATION).delete_many({'personId': str(account['_id']), 'kind': 'account'})
    col(schema.VERIFICATION).insert_one({
        'personId': str(account['_id']),
        'name': display_name(_reload(account)),
        'type': role,
        'kind': 'account',
        'submitted': iso(),
        'checks': checks,
    })
    return {'status': 'pending'}


# ── Closing an account ──────────────────────────────────────────────────
@router.post('/api/users/me/deactivate')
async def deactivate(body: CloseBody, account: dict = Depends(creator_or_brand)):
    _set(account, {'status': 'deactivated', 'deactivation': {'reason': body.reason, 'feedback': body.feedback, 'at': iso()}})
    return {'status': 'deactivated'}


@router.delete('/api/users/me')
async def request_deletion(body: DeleteBody, account: dict = Depends(creator_or_brand)):
    """Ask for deletion. The data is erased by a job once active deals are finished."""
    if body.confirm != 'DELETE MY ACCOUNT':
        raise HTTPException(422, 'Type DELETE MY ACCOUNT to confirm.')
    _set(account, {
        'status': 'deactivated',
        'deletionRequestedAt': iso(),
        'deletion': {'reason': body.reason, 'feedback': body.feedback},
    })
    return {'status': 'deletion-requested'}


# Instagram / Facebook verification by DM code and invite links: routes/social_verify.py


# ── Brand work email ─────────────────────────────────────────────────────
@router.post('/api/verification/business-email')
async def send_work_email_code(body: WorkEmailBody, tasks: BackgroundTasks, account: dict = Depends(brand_account)):
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(422, 'Enter a valid email address.')
    if email.split('@')[1] in FREE_MAIL:
        raise HTTPException(422, 'Use your company email. Personal addresses like Gmail can’t verify a brand.')
    _issue_code(email, 'work-email', str(account['_id']), tasks, 'Confirm your work email for OPC', 'Use this code to confirm your work email on OPC.')
    return {'sent': True}


@router.post('/api/verification/confirm-email')
async def confirm_work_email(body: ConfirmEmailBody, account: dict = Depends(brand_account)):
    email = body.email.strip().lower()
    _check_code({'email': email, 'purpose': 'work-email', 'accountId': str(account['_id'])}, body.code)
    _set(account, {'profile.workEmail': email, 'emailVerified': True})
    return {'verified': True}
