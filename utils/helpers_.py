"""Small shared helpers for the dashboard API: time, ids, roles, JSON, audit, notifications."""
from datetime import datetime, timezone, timedelta
from bson import ObjectId
from pymongo import ReturnDocument

from database.config import client
from database import schema


def col(where: tuple):
    """Collection for a (database, collection) pair from database/schema.py."""
    db, name = where
    # In MongoDB Atlas, 'admin' / 'ADMIN' is a system-reserved database name that
    # standard database users cannot access. Map 'ADMIN' to 'OPC_ADMIN' on real
    # MongoDB clusters, while keeping 'ADMIN' in mongomock tests.
    if db == 'ADMIN' and not type(client).__module__.startswith('mongomock'):
        db = 'OPC_ADMIN'
    return client[db][name]


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None = None) -> str:
    return (dt or now()).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def iso_in(days: int = 0, minutes: int = 0) -> str:
    return iso(now() + timedelta(days=days, minutes=minutes))


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def oid(value: str):
    """ObjectId when the string is one, else the string (older docs used string ids)."""
    try:
        return ObjectId(value)
    except Exception:
        return value


def ser(value):
    """Make a Mongo document JSON-safe: ObjectId -> str, datetime -> ISO string, `_id` -> `id`."""
    if isinstance(value, list):
        return [ser(v) for v in value]
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k == '_id':
                out['id'] = str(v)
            elif k in ('code_hash',):
                continue
            else:
                out[k] = ser(v)
        return out
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return iso(value if value.tzinfo else value.replace(tzinfo=timezone.utc))
    return value


def next_code(prefix: str, width: int = 3) -> str:
    """Readable sequential codes such as DSP-007 or TKT-045."""
    doc = col(schema.COUNTERS).find_one_and_update(
        {'_id': prefix}, {'$inc': {'seq': 1}}, upsert=True, return_document=ReturnDocument.AFTER
    )
    return f"{prefix}-{str(doc['seq']).zfill(width)}"


def deal_code() -> str:
    """Contract ids like OPC-2026-1117-004 (date + daily sequence)."""
    today = now().strftime('%Y-%m%d')
    seq = next_code(f'DEAL-{today}').split('-')[-1]
    return f"OPC-{today}-{seq}"


# ── Roles ────────────────────────────────────────────────────────────────
ROLE_ALIASES = {
    'creator': 'creator',
    'brand': 'brand',
    'event partner': 'event_partner',
    'event_partner': 'event_partner',
    'eventpartner': 'event_partner',
    'team': 'team',
}

# Account types that are platform members. "team" accounts belong to the OPC team
# (created when a team email signs in for the first time) and aren't listed as people.
MEMBER_ROLES = ('creator', 'brand', 'event_partner')


def role_of(account: dict) -> str:
    """Normalise user_type: sign-in stores button text such as "Event Partner"."""
    raw = str(account.get('user_type', '')).strip().lower()
    return ROLE_ALIASES.get(raw, raw.replace(' ', '_'))


def display_name(account: dict) -> str:
    p = account.get('profile') or {}
    if role_of(account) == 'creator':
        return p.get('legalName') or p.get('displayName') or account.get('email', '')
    return p.get('company') or account.get('email', '')


def handle_of(account: dict) -> str:
    p = account.get('profile') or {}
    return p.get('displayName') or ''


def status_of(account: dict) -> str:
    return account.get('status') or 'active'


# ── Side effects shared by every module ─────────────────────────────────
def audit(actor: str, action: str, target: str) -> None:
    """Team console audit log. Insert-only: nothing updates or deletes these."""
    try:
        col(schema.AUDIT).insert_one({'actor': actor, 'action': action, 'target': target, 'at': iso()})
    except Exception as e:
        print(f"[AUDIT WARNING] Failed to record audit log: {e}")


def open_conversation(brand: dict, creator: dict, subject: str, deal_code: str | None = None) -> str:
    """Start (or return) the chat between a brand and a creator. Used when a brand reveals a creator."""
    existing = col(schema.CONVERSATIONS).find_one(
        {'members.accountId': {'$all': [str(brand['_id']), str(creator['_id'])]}, 'dealId': deal_code}
    )
    if existing:
        return str(existing['_id'])
    doc = {
        'members': [
            {'accountId': str(brand['_id']), 'name': display_name(brand), 'type': 'brand'},
            {'accountId': str(creator['_id']), 'name': display_name(creator), 'type': 'creator'},
        ],
        'subject': subject,
        'dealId': deal_code,
        'flagged': False,
        'suspended': False,
        'lastAt': iso(),
        'unread': {},
    }
    return str(col(schema.CONVERSATIONS).insert_one(doc).inserted_id)


def notify(account_id, text: str) -> None:
    col(schema.NOTIFICATIONS).insert_one({'accountId': str(account_id), 'text': text, 'at': iso(), 'read': False})
