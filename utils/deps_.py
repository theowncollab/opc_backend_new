"""
FastAPI dependencies for the dashboard API (/api/*).

- The login token is accepted from the `Authorization: Bearer` header OR the
  `accessToken` cookie, so the dashboard works with today's sign-in (which stores
  tokens in cookies) and with HttpOnly cookies later.
- Errors are real HTTP status codes with {"detail": "..."}; the dashboard's
  api() shows `detail` / `message` to the user.
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Literal

import jwt
from fastapi import Depends, HTTPException, Query, Request

from database import schema
from utils.auth_settings_ import settings
from utils.helpers_ import col, iso, oid, role_of, status_of
from utils.permissions_ import can

Role = Literal['creator', 'brand']


def token_from_request(request: Request) -> str | None:
    header = request.headers.get('authorization', '')
    if header.lower().startswith('bearer '):
        token = header[7:].strip()
        if token and token not in ('null', 'undefined'):
            return token
    return request.cookies.get('accessToken')


def current_user(request: Request) -> dict:
    """The account the token was issued for. 401 if missing, expired or logged out."""
    token = token_from_request(request)
    if not token:
        raise HTTPException(401, 'Sign in to continue.')
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except Exception:
        raise HTTPException(401, 'Your session has ended. Sign in again.')
    account = col(schema.USERS).find_one({'_id': oid(str(payload.get('sub')))})
    if not account:
        raise HTTPException(401, 'Account not found. Sign in again.')
    last_logout = account.get('last_logout_time')
    if last_logout and payload.get('iat'):
        if last_logout.tzinfo is None:
            last_logout = last_logout.replace(tzinfo=timezone.utc)
        issued = datetime.fromtimestamp(payload['iat'], tz=timezone.utc)
        if issued < last_logout - timedelta(seconds=1):
            raise HTTPException(401, 'You signed out. Sign in again.')
    col(schema.USERS).update_one({'_id': account['_id']}, {'$set': {'lastActive': iso()}})
    return account


def account_for_role(user: dict, role: str) -> dict:
    """The signed-in person's account for `role` (same email, one account per role)."""
    if role_of(user) == role:
        account = user
    else:
        account = next((a for a in col(schema.USERS).find({'email': user['email']}) if role_of(a) == role), None)
    if not account:
        raise HTTPException(404, f'You don’t have a {role} account. Sign up as a {role} first.')
    if status_of(account) == 'suspended':
        raise HTTPException(403, 'This account is suspended. Contact support@theowncollab.com.')
    return account


async def creator_or_brand(
    role: Role = Query('creator', description='Which of your accounts to use: creator or brand'),
    user: dict = Depends(current_user),
) -> dict:
    """`?role=creator|brand` -> that account of the signed-in person."""
    return account_for_role(user, role)


async def creator_account(user: dict = Depends(current_user)) -> dict:
    return account_for_role(user, 'creator')


async def brand_account(user: dict = Depends(current_user)) -> dict:
    return account_for_role(user, 'brand')


# ── OPC team ─────────────────────────────────────────────────────────────
def _owner_emails() -> set[str]:
    """Bootstrap owners from the env so the first person can get in: STAFF_OWNER_EMAILS=a@x.com,b@x.com"""
    return {e.strip().lower() for e in os.getenv('STAFF_OWNER_EMAILS', 'ceo@theowncollab.com').split(',') if e.strip()}


def staff_member(user: dict = Depends(current_user)) -> dict:
    """The signed-in person's team record. 403 unless they're on the OPC team."""
    email = user['email'].lower()
    member = col(schema.TEAM).find_one({'email': email})
    if not member and email in _owner_emails():
        member = {'email': email, 'name': email.split('@')[0].title(), 'role': 'Owner', 'invited': False}
        col(schema.TEAM).insert_one(dict(member))
        member = col(schema.TEAM).find_one({'email': email})
    if not member:
        raise HTTPException(403, 'This area is for the OPC team.')
    col(schema.TEAM).update_one({'_id': member['_id']}, {'$set': {'lastActive': iso(), 'invited': False}})
    return member


def require(permission: str):
    """Dependency factory: the team member must have `permission` (utils/permissions_.py)."""
    def _dep(member: dict = Depends(staff_member)) -> dict:
        if not can(member.get('role', ''), permission):
            raise HTTPException(403, f"Your role ({member.get('role')}) can’t do this.")
        return member
    return _dep


def cron_secret(request: Request) -> None:
    """Scheduled jobs: Vercel Cron sends `Authorization: Bearer $CRON_SECRET`."""
    expected = os.getenv('CRON_SECRET')
    if not expected or request.headers.get('authorization') != f'Bearer {expected}':
        raise HTTPException(401, 'Not allowed.')
