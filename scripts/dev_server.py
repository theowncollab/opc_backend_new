"""
Run the backend locally with no database and no email account.

    .venv/Scripts/python scripts/dev_server.py        (Windows)
    .venv/bin/python scripts/dev_server.py            (macOS / Linux)

- MongoDB is replaced by an in-memory database (mongomock); data is lost on exit.
- Emails are printed to the console instead of being sent.
- Demo accounts are created through the real API (a campaign, a revealed creator,
  a deal in review, a ticket and a Facebook code request), so the
  dashboard has something to show. Sign-in tokens are written to
  scripts/.dev_tokens.json (git-ignored). In the browser on the dashboard's
  address, set them with:  document.cookie = "accessToken=<token>; path=/"

NEVER use this in production.
"""
import json
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

os.environ.setdefault('ENVIRONMENT', 'DEVELOPMENT')
os.environ.setdefault('DB_USER', 'dev')
os.environ.setdefault('DB_PASSWORD', 'dev')
os.environ.setdefault('SMTP_USER', 'support@theowncollab.com')
os.environ.setdefault('SMTP_PASSWORD', 'dev')
os.environ.setdefault('SMTP_PORT', '587')
os.environ.setdefault('SMTP_SERVER', 'localhost')
os.environ.setdefault('STAFF_OWNER_EMAILS', 'ceo@theowncollab.com')
os.environ.setdefault('CRON_SECRET', 'dev-cron-secret')
os.environ.setdefault('GOOGLE_CLIENT_ID', '828246651523-ulnokv5h94loanmj3pd8t8ud6kc72ov5.apps.googleusercontent.com')  # public ID, same as the website's

import mongomock  # noqa: E402

fake = types.ModuleType('database.config')
fake.client = mongomock.MongoClient()
sys.modules['database.config'] = fake

import jwt  # noqa: E402
import uvicorn  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from utils import email_  # noqa: E402
from utils.auth_settings_ import settings  # noqa: E402


async def print_email(to_, from_, subject_, body_):
    print(f'\n[email] to {to_}: {subject_}\n')


email_.send_email_async = print_email

from main import app  # noqa: E402

DB = fake.client


def token(account_id) -> str:
    now = datetime.now(timezone.utc)
    t = jwt.encode({'sub': str(account_id), 'iat': now, 'exp': now + timedelta(days=7)}, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return t.decode() if isinstance(t, bytes) else t


def account(email, user_type, profile, **extra):
    doc = {
        'email': email, 'user_type': user_type, 'last_logout_time': None, 'status': 'active', 'verified': True,
        'joined': '2026-11-02T09:00:00Z', 'profile': profile,
        'onboarding': {'step': 4, 'data': {}, 'completedAt': '2026-11-08T09:00:00Z'},
        'signature': {'mode': 'type', 'typed': profile.get('legalName') or profile.get('signatory', ''), 'consentVersion': '2026-11-17'},
    }
    doc.update(extra)
    return DB['USERS']['PERM_USERS'].insert_one(doc).inserted_id


def seed() -> dict:
    creator = account('priya@email.com', 'Creator',
                      {'legalName': 'Priya Sharma', 'displayName': '@priya_creates', 'city': 'Mumbai', 'niche': 'Fashion & Lifestyle', 'phone': '+91 98765 43210'},
                      iis=28, iisFactors={'engagement': 8.4, 'quality': 7.5, 'reliability': 6.5, 'growth': 5.6},
                      socials=[{'platform': 'instagram', 'handle': '@priya_creates', 'followers': 45000, 'verified': True, 'verifiedOn': '2026-11-08'}])
    account('sneha.m@email.com', 'Creator',
            {'legalName': 'Sneha Mehra', 'displayName': '@sneha_style', 'city': 'Mumbai', 'niche': 'Fashion & Lifestyle'},
            iis=62, socials=[{'platform': 'instagram', 'handle': '@sneha_style', 'followers': 52000, 'verified': True, 'verifiedOn': '2026-11-05'}])
    brand = account('ananya@stylekart.in', 'Brand',
                    {'company': 'StyleKart Fashion Pvt. Ltd.', 'industry': 'Fashion & Apparel', 'contact': 'Ananya Mehta', 'designation': 'Marketing Manager',
                     'city': 'Mumbai', 'website': 'https://stylekart.in', 'signatory': 'Rohan Kapoor', 'workEmail': 'ananya@stylekart.in'},
                    emailVerified=True)
    staff = account('ceo@theowncollab.com', 'Brand', {'company': 'OPC'})
    # OPC's own Gmail: a permanent console Owner (utils/deps_.py PERMANENT_OWNERS)
    opc = account('opc.owncollab@gmail.com', 'Brand', {'company': 'OPC'})
    newcomer = account('arjun.nair@email.com', 'Creator', {'legalName': 'Arjun Nair', 'displayName': '@arjun.eats', 'city': 'Kochi', 'niche': 'Food & Beverages'},
                       status='pending', verified=False)
    DB['MEET']['TIMINGS'].insert_one({'time_slots': ['10:00', '10:30', '11:00', '11:30', '15:00', '15:30', '16:00']})

    # 'newcomer' has no verified Instagram, for trying an invite link.
    tokens = {'creator': token(creator), 'brand': token(brand), 'staff': token(staff), 'newcomer': token(newcomer), 'opc': token(opc)}
    c = TestClient(app)
    h = {k: {'Authorization': f'Bearer {v}'} for k, v in tokens.items()}

    def ok(r):
        assert r.status_code < 400, f'{r.request.method} {r.request.url} -> {r.status_code} {r.text}'
        return r.json()

    camp = ok(c.post('/api/campaigns?role=brand', headers=h['brand'], json={
        'objective': 'Brand awareness', 'name': 'FashionFest Winter 2026', 'age': '18–24', 'gender': 'Women', 'cities': 'Mumbai, Delhi',
        'budget': '5000', 'payType': 'Paid (cash)', 'contentType': 'Reels and short videos', 'creators': '1', 'niche': 'Fashion and lifestyle',
        'deadline': '2026-11-30', 'kpi': 'Views and impressions', 'kpiValue': '100000', 'platforms': ['instagram'], 'status': 'matching'}))
    matches = ok(c.get(f"/api/campaigns/{camp['id']}/matches?role=brand", headers=h['brand']))
    priya = next(m for m in matches if m['iis'] == 28)
    deal = ok(c.post(f"/api/discover/creators/{priya['id']}/reveal?role=brand", headers=h['brand'], json={'campaignId': camp['id']}))
    for stage in ['finalised', 'signed', 'timeline', 'brief', 'script', 'scriptApproved', 'contentMade']:
        ok(c.post(f"/api/admin/deals/{deal['dealId']}/stage", headers=h['staff'], json={'stage': stage}))
    ok(c.post(f"/api/deals/{deal['dealId']}/submit-content?role=creator", headers=h['creator'], json={'link': 'https://instagram.com/reel/demo'}))
    convs = ok(c.get('/api/chat/conversations?role=creator', headers=h['creator']))
    ok(c.post(f"/api/chat/conversations/{convs[0]['id']}/send?role=brand", headers=h['brand'], json={'text': 'Hi Priya! The brief is in your inbox.'}))
    ok(c.post(f"/api/chat/conversations/{convs[0]['id']}/send?role=creator", headers=h['creator'], json={'text': 'Thanks! Reel submitted for review.'}))
    ok(c.post('/api/support/tickets?role=creator', headers=h['creator'], json={'category': 'Payment', 'subject': 'When do payments start?', 'body': 'I want to know when online payouts will be available for my deals.'}))
    ok(c.post('/api/users/me/socials/request-code?role=creator', headers=h['creator'], json={'platform': 'facebook', 'handle': 'facebook.com/priya.creates'}))
    # A meeting request from the website, waiting for the team to email the link
    tomorrow = c.get('/api/meetings/slots').json()['date']
    ok(c.post('/api/meetings/book', json={'name': 'Rahul Verma', 'email': 'rahul@fitfuel.co.in', 'phone': '+91 98200 11223', 'userType': 'brand',
                                         'company': 'FitFuel Nutrition', 'topic': 'Planning a creator campaign for our new protein bars.',
                                         'date': tomorrow, 'time': '19:30'}))
    # Website inbox: a contact message, a registered event and a newsletter sign-up
    ok(c.post('/contact-us', json={'name': 'Kabir Malhotra', 'email': 'kabir@brewcafe.in', 'subject': 'Food creators in Pune',
                                   'message': 'We run three cafés in Pune and want 4–5 food creators for our winter menu. Can OPC help?'}))
    ok(c.post('/register-event', json={'name': 'Mood Indigo 2026', 'start_date': '2026-12-20T10:00', 'end_date': '2026-12-23T22:00',
                                       'organizer': 'IIT Bombay', 'location': 'Mumbai', 'poc_email': 'sponsors@moodi.in',
                                       'poc_name': 'Rhea Kapoor', 'poc_phone': 9876543210}))
    ok(c.post('/api/newsletter', json={'email': 'neha.styles@gmail.com'}))
    return tokens


if __name__ == '__main__':
    tokens = seed()
    out = ROOT / 'scripts' / '.dev_tokens.json'
    out.write_text(json.dumps(tokens, indent=2))
    print(f'\nDemo data ready. Tokens for creator, brand and staff (ceo@theowncollab.com) written to {out}')
    uvicorn.run(app, host='127.0.0.1', port=int(os.getenv('PORT', '8000')), log_level='warning')
