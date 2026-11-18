"""
Test harness for the dashboard API.

- MongoDB is replaced by mongomock (in memory), so tests need no database or .env.
- Email sending is captured in the `mails` fixture instead of being sent.
- `make_account` / `auth` / `staff` create people and sign them in.

Run:  .venv/Scripts/python -m pytest -q        (Windows)
      .venv/bin/python -m pytest -q            (macOS / Linux)
"""
import os
import sys
import types
from datetime import datetime, timedelta, timezone

import mongomock
import pytest

# Environment the app reads at import time.
os.environ.setdefault('DB_USER', 'test')
os.environ.setdefault('DB_PASSWORD', 'test')
os.environ.setdefault('SMTP_USER', 'noreply@theowncollab.com')
os.environ.setdefault('SMTP_PASSWORD', 'x')
os.environ.setdefault('SMTP_PORT', '587')
os.environ.setdefault('SMTP_SERVER', 'smtp.example.com')
os.environ.setdefault('STAFF_OWNER_EMAILS', 'owner@theowncollab.com')
os.environ.setdefault('CRON_SECRET', 'test-cron-secret')

# Swap the real MongoClient for an in-memory one before anything imports it.
_fake_config = types.ModuleType('database.config')
_fake_config.client = mongomock.MongoClient()
sys.modules['database.config'] = _fake_config

import jwt  # noqa: E402
from bson import ObjectId  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from utils import email_  # noqa: E402
from utils.auth_settings_ import settings  # noqa: E402

DB = _fake_config.client


@pytest.fixture(autouse=True)
def clean_db():
    for name in DB.list_database_names():
        DB.drop_database(name)
    yield


@pytest.fixture
def mails(monkeypatch):
    sent = []

    async def fake_send(to_, from_, subject_, body_):
        sent.append({'to': to_, 'from': from_, 'subject': subject_, 'body': body_})

    monkeypatch.setattr(email_, 'send_email_async', fake_send)
    return sent


@pytest.fixture
def client(mails):
    from main import app
    return TestClient(app)


def _token(account_id: str) -> str:
    now = datetime.now(timezone.utc)
    t = jwt.encode({'sub': str(account_id), 'iat': now, 'exp': now + timedelta(minutes=30)}, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return t.decode() if isinstance(t, bytes) else t


@pytest.fixture
def make_account():
    """make_account('priya@x.com', 'creator', profile={...}, status='active') -> account id (str)."""
    def _make(email: str, role: str, **fields) -> str:
        user_type = {'creator': 'Creator', 'brand': 'Brand', 'event_partner': 'Event Partner'}[role]
        doc = {'email': email, 'user_type': user_type, 'last_logout_time': None, 'status': 'active', 'verified': True, 'joined': '2026-11-01T09:00:00Z', 'profile': {}}
        doc.update(fields)
        return str(DB['USERS']['PERM_USERS'].insert_one(doc).inserted_id)
    return _make


@pytest.fixture
def auth():
    """auth(account_id) -> headers that sign that account in."""
    return lambda account_id: {'Authorization': f'Bearer {_token(account_id)}'}


@pytest.fixture
def staff(make_account, auth):
    """staff('Finance') -> headers for a signed-in team member with that role."""
    def _staff(role: str = 'Owner', email: str | None = None):
        email = email or f'{role.lower()}@theowncollab.com'
        account_id = make_account(email, 'brand')
        DB['ADMIN']['TEAM'].insert_one({'email': email, 'name': role, 'role': role, 'invited': False})
        return auth(account_id)
    return _staff


@pytest.fixture
def db():
    return DB


def oid(value: str):
    return ObjectId(value)
