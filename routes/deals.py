"""
Dashboard API, section B: campaigns (with the readiness score worked out here),
creator matches, revealing a creator (which starts a deal and the 6-month
protection window), the deal steps a creator or brand takes, and the job that
auto-approves content when the review window ends. Contract: DASHBOARD_API.md.
"""
import calendar
import re
from datetime import datetime, timedelta
from typing import Literal, Optional, Union

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from database import schema
from utils import fees_
from utils.deps_ import brand_account, creator_account, creator_or_brand, cron_secret
from utils.helpers_ import (
    col, deal_code, display_name, handle_of, iso, next_code, notify, now, oid,
    open_conversation, parse_iso, role_of, status_of,
)

router = APIRouter()

PLATFORMS = {'instagram', 'youtube', 'x', 'facebook', 'linkedin', 'moj'}
LOCKED_FOR_SUBMIT = {'review', 'verify', 'paid'}

# Typical deal size per IIS tier, used for the budget-fit part of the match score.
TIER_MIN_DEAL = [(85, 70000), (65, 20000), (40, 5000), (0, 1000)]


# ── Shapes ───────────────────────────────────────────────────────────────
def _grace_day(deal: dict) -> int | None:
    start = deal.get('graceStartedOn')
    if not start:
        return None
    hold = fees_.GRACE_TIERS[fees_.tier_for_ris(int(deal.get('ris') or 0))]['holdDays']
    return max(1, min(hold, (now() - parse_iso(start)).days + 1))


def deal_out(deal: dict) -> dict:
    """`Deal` in dashboard-app/src/data/types.ts."""
    out = {
        'id': deal['code'],
        'campaignName': deal.get('campaignName', ''),
        'brandName': deal.get('brandName', ''),
        'creatorName': deal.get('creatorName', ''),
        'creatorHandle': deal.get('creatorHandle', ''),
        'deliverable': deal.get('deliverable', ''),
        'platform': deal.get('platform', 'instagram'),
        'budget': int(deal.get('budget') or 0),
        'ris': int(deal.get('ris') or 0),
        'stage': deal.get('stage', 'selected'),
        'deadline': deal.get('deadline') or '',
        'signedOn': deal.get('signedOn') or '',
        'flaggedChat': bool(deal.get('flaggedChat')),
    }
    if deal.get('graceStartedOn'):
        out['graceEndsOn'] = deal.get('graceEndsOn')
        out['graceDay'] = _grace_day(deal)
    return out


def campaign_out(c: dict) -> dict:
    """`Campaign` in dashboard-app/src/data/types.ts."""
    return {
        'id': str(c['_id']),
        'name': c.get('name', ''),
        'status': c.get('status', 'draft'),
        'budget': int(c.get('budget') or 0),
        'platforms': c.get('platforms') or [],
        'creators': int(c.get('creators') or 0),
        'cirs': int(c.get('cirs') or 0),
        'deadline': c.get('deadline') or '',
    }


# ── Helpers ──────────────────────────────────────────────────────────────
def _int(value) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    digits = re.sub(r'[^\d]', '', str(value or ''))
    return int(digits) if digits else 0


def _band_low(band: str) -> int:
    """'2–3' -> 2, '10+' -> 10, '' -> 0."""
    m = re.search(r'\d+', str(band or ''))
    return int(m.group()) if m else 0


def _add_months(dt: datetime, months: int) -> datetime:
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def _norm(text: str) -> str:
    return re.sub(r'[^a-z ]', '', str(text or '').lower().replace('&', 'and')).strip()


def _find_deal(code: str, account: dict) -> dict:
    """The deal, if this account is the brand or the creator on it. 404 otherwise."""
    deal = col(schema.DEALS).find_one({'code': code})
    me = str(account['_id'])
    if not deal or me not in (deal.get('brandAccountId'), deal.get('creatorAccountId')):
        raise HTTPException(404, 'Deal not found.')
    return deal


def _update_deal(deal: dict, fields: dict, unset: Optional[list] = None, push: Optional[dict] = None) -> dict:
    op: dict = {'$set': {**fields, 'updatedAt': iso()}}
    if unset:
        op['$unset'] = {k: '' for k in unset}
    if push:
        op['$push'] = push
    col(schema.DEALS).update_one({'_id': deal['_id']}, op)
    return col(schema.DEALS).find_one({'_id': deal['_id']})


def cirs_of(f: dict) -> int:
    """Campaign readiness score; same formula as PostCampaign.tsx (section maxima 10/15/20/15/20)."""
    has = lambda k: bool(str(f.get(k) or '').strip())  # noqa: E731
    obj = 10 if has('objective') else 0
    aud = (4 if has('age') else 0) + (4 if has('gender') else 0) + (4 if has('cities') else 0) + (3 if has('persona') else 0)
    bud = (13 if _int(f.get('budget')) > 0 else 0) + (7 if has('payType') else 0)
    dlv = (6 if f.get('platforms') else 0) + (5 if has('contentType') else 0) + (4 if has('creators') else 0)
    met = (8 if has('deadline') else 0) + (7 if has('kpi') else 0) + (5 if has('kpiValue') else 0)
    return min(100, obj + aud + bud + dlv + met)


def _brand_campaign(campaign_id: str, brand: dict) -> dict:
    try:
        cid = ObjectId(campaign_id)
    except Exception:
        raise HTTPException(404, 'Campaign not found.')
    campaign = col(schema.CAMPAIGNS).find_one({'_id': cid, 'brandAccountId': str(brand['_id'])})
    if not campaign:
        raise HTTPException(404, 'Campaign not found.')
    return campaign


# ── Request bodies ───────────────────────────────────────────────────────
class SubmitBody(BaseModel):
    link: str
    note: Optional[str] = None


class NoteBody(BaseModel):
    note: str = Field(min_length=5)


class DisputeBody(BaseModel):
    note: str = Field(min_length=10)


class CampaignInput(BaseModel):
    objective: str = ''
    name: str = Field(min_length=1, max_length=120)
    description: str = ''
    age: str = ''
    gender: str = ''
    cities: str = ''
    persona: str = ''
    product: str = ''
    price: str = ''
    usp: str = ''
    budget: Union[str, int, float] = ''
    payType: str = ''
    contentType: str = ''
    creators: str = ''
    tier: str = ''
    niche: str = ''
    deadline: str = ''
    kpi: str = ''
    kpiValue: str = ''
    notes: str = ''
    platforms: list[str] = Field(default_factory=list)
    status: Literal['draft', 'matching'] = 'draft'


class RevealBody(BaseModel):
    campaignId: str


# ── Deals ────────────────────────────────────────────────────────────────
@router.get('/api/deals')
async def list_deals(account: dict = Depends(creator_or_brand)):
    """Deals where you're the brand or the creator (`?role=`), newest first."""
    field = 'creatorAccountId' if role_of(account) == 'creator' else 'brandAccountId'
    deals = col(schema.DEALS).find({field: str(account['_id'])}).sort('updatedAt', -1)
    return [deal_out(d) for d in deals]


@router.get('/api/deals/{code}')
async def get_deal(code: str, account: dict = Depends(creator_or_brand)):
    return deal_out(_find_deal(code, account))


@router.post('/api/deals/{code}/submit-content')
async def submit_content(code: str, body: SubmitBody, creator: dict = Depends(creator_account)):
    """The creator sends a link to the content. This starts the brand's review window."""
    deal = _find_deal(code, creator)
    if deal.get('creatorAccountId') != str(creator['_id']):
        raise HTTPException(404, 'Deal not found.')
    if not body.link.strip().startswith('https://'):
        raise HTTPException(422, 'Share a link that starts with https://.')
    if deal.get('stage') in LOCKED_FOR_SUBMIT:
        raise HTTPException(409, 'Content for this deal is already with the brand.')
    hold_days = fees_.GRACE_TIERS[fees_.tier_for_ris(int(deal.get('ris') or 0))]['holdDays']
    started = now()
    deal = _update_deal(
        deal,
        {'stage': 'review', 'graceStartedOn': iso(started), 'graceEndsOn': iso(started + timedelta(days=hold_days))},
        push={'submissions': {'link': body.link.strip(), 'note': body.note, 'at': iso(started)}},
    )
    notify(deal['brandAccountId'], f"{deal['creatorName']} submitted content for {deal['campaignName']}. Review it within {hold_days} days.")
    return deal_out(deal)


def _brand_deal(code: str, brand: dict) -> dict:
    deal = _find_deal(code, brand)
    if deal.get('brandAccountId') != str(brand['_id']):
        raise HTTPException(404, 'Deal not found.')
    return deal


@router.post('/api/deals/{code}/approve')
async def approve_content(code: str, brand: dict = Depends(brand_account)):
    deal = _brand_deal(code, brand)
    if deal.get('stage') != 'review':
        raise HTTPException(409, 'There’s no content waiting for your review on this deal.')
    deal = _update_deal(deal, {'stage': 'verify', 'approvedAt': iso()})
    notify(deal['creatorAccountId'], f"{deal['brandName']} approved your content for {deal['campaignName']}.")
    return deal_out(deal)


@router.post('/api/deals/{code}/request-revision')
async def request_revision(code: str, body: NoteBody, brand: dict = Depends(brand_account)):
    deal = _brand_deal(code, brand)
    if deal.get('stage') != 'review':
        raise HTTPException(409, 'You can only ask for a revision while reviewing submitted content.')
    if len(deal.get('revisions') or []) >= 1:
        raise HTTPException(409, "This deal's one revision has been used.")
    deal = _update_deal(
        deal,
        {'stage': 'scriptApproved'},
        unset=['graceStartedOn', 'graceEndsOn'],
        push={'revisions': {'note': body.note, 'at': iso()}},
    )
    notify(deal['creatorAccountId'], f"{deal['brandName']} asked for a revision on {deal['campaignName']}: {body.note}")
    return deal_out(deal)


@router.post('/api/deals/{code}/dispute')
async def raise_dispute(code: str, body: DisputeBody, account: dict = Depends(creator_or_brand)):
    deal = _find_deal(code, account)
    if col(schema.DISPUTES).find_one({'dealId': deal['code'], 'status': 'open'}):
        raise HTTPException(409, 'A dispute is already open for this deal.')
    role = role_of(account)
    split = fees_.split_budget(int(deal.get('budget') or 0), fees_.tier_for_ris(int(deal.get('ris') or 0)))
    dispute_id = next_code('DSP')
    col(schema.DISPUTES).insert_one({
        'code': dispute_id,
        'dealId': deal['code'],
        'campaign': deal.get('campaignName', ''),
        'brand': deal.get('brandName', ''),
        'creator': deal.get('creatorName', ''),
        'raisedBy': role,
        'raisedByAccountId': str(account['_id']),
        'reason': body.note,
        'held': split['hold'],
        'opened': iso(),
        'status': 'open',
        'evidence': [],
        'outcome': None,
    })
    other = deal['creatorAccountId'] if role == 'brand' else deal['brandAccountId']
    notify(other, f"A dispute was raised on {deal['campaignName']}. OPC will review it within 24 hours.")
    return {'disputeId': dispute_id}


# ── Campaigns ────────────────────────────────────────────────────────────
def _campaign_fields(body: CampaignInput) -> dict:
    brief = body.model_dump()
    cirs = cirs_of(brief)
    if body.status == 'matching' and cirs < 40:
        raise HTTPException(422, f'Add more detail first. Briefs need a readiness score of 40 to be matched, and this one scores {cirs}.')
    return {
        'name': body.name.strip(),
        'status': body.status,
        'budget': _int(body.budget),
        'platforms': body.platforms,
        'creators': _band_low(body.creators),
        'cirs': cirs,
        'deadline': body.deadline,
        'brief': brief,
        'updatedAt': iso(),
    }


@router.post('/api/campaigns')
async def create_campaign(body: CampaignInput, brand: dict = Depends(brand_account)):
    fields = _campaign_fields(body)
    doc = {**fields, 'brandAccountId': str(brand['_id']), 'brandName': display_name(brand), 'createdAt': iso()}
    doc['_id'] = col(schema.CAMPAIGNS).insert_one(doc).inserted_id
    return campaign_out(doc)


@router.put('/api/campaigns/{campaign_id}')
async def update_campaign(campaign_id: str, body: CampaignInput, brand: dict = Depends(brand_account)):
    campaign = _brand_campaign(campaign_id, brand)
    if campaign.get('status') not in ('draft', 'matching'):
        raise HTTPException(409, 'This campaign is already running, so its brief can’t be changed.')
    col(schema.CAMPAIGNS).update_one({'_id': campaign['_id']}, {'$set': _campaign_fields(body)})
    return campaign_out(col(schema.CAMPAIGNS).find_one({'_id': campaign['_id']}))


@router.get('/api/campaigns')
async def list_campaigns(brand: dict = Depends(brand_account)):
    return [campaign_out(c) for c in col(schema.CAMPAIGNS).find({'brandAccountId': str(brand['_id'])}).sort('updatedAt', -1)]


# ── Matching and reveal ──────────────────────────────────────────────────
def _followers(creator: dict) -> int:
    return sum(int(s.get('followers') or 0) for s in (creator.get('socials') or []) if s.get('verified'))


def _cifs(creator: dict, campaign: dict) -> int:
    """Simplified creator-campaign fit (0–100): 35 % IIS + 20 niche + 15 city + 15 budget fit + 15 % CIRS."""
    brief = campaign.get('brief') or {}
    profile = creator.get('profile') or {}
    iis = int(creator.get('iis') or 0)
    score = 35 * iis / 100

    want, have = _norm(brief.get('niche')), _norm(profile.get('niche'))
    if want and have and (want == have or want.split()[0] == have.split()[0]):
        score += 20

    cities = [_norm(c) for c in str(brief.get('cities') or '').split(',') if c.strip()]
    home = _norm(str(profile.get('city') or '').split(',')[0])
    if home and home in cities:
        score += 15

    per_creator = int(campaign.get('budget') or 0) / max(1, int(campaign.get('creators') or 1))
    tier_min = next(m for floor, m in TIER_MIN_DEAL if iis >= floor)
    score += 15 * min(1.0, per_creator / tier_min) if tier_min else 15

    score += 15 * int(campaign.get('cirs') or 0) / 100
    return min(100, round(score))


@router.get('/api/campaigns/{campaign_id}/matches')
async def campaign_matches(campaign_id: str, brand: dict = Depends(brand_account)):
    """Top 10 anonymous creator matches. Names show only after a reveal."""
    campaign = _brand_campaign(campaign_id, brand)
    creators = [
        a for a in col(schema.USERS).find({})
        if role_of(a) == 'creator' and status_of(a) == 'active' and a.get('verified')
    ]
    ranked = sorted(creators, key=lambda a: _cifs(a, campaign), reverse=True)[:10]
    revealed = {
        r['creatorAccountId']: r
        for r in col(schema.REVEALS).find({'campaignId': str(campaign['_id']), 'brandAccountId': str(brand['_id'])})
    }
    out = []
    for i, a in enumerate(ranked):
        profile = a.get('profile') or {}
        match = {
            'id': str(a['_id']),
            'alias': f'Creator {chr(65 + i)}',
            'niche': profile.get('niche', ''),
            'topCity': str(profile.get('city') or '').split(',')[0].strip(),
            'followers': _followers(a),
            'engagementRate': float(a.get('engagementRate') or 0),
            'iis': int(a.get('iis') or 0),
            'cifs': _cifs(a, campaign),
        }
        r = revealed.get(str(a['_id']))
        if r:
            match['revealed'] = {'name': r.get('creatorName', ''), 'handle': r.get('creatorHandle', '')}
        out.append(match)
    return out


@router.post('/api/discover/creators/{creator_id}/reveal')
async def reveal_creator(creator_id: str, body: RevealBody, brand: dict = Depends(brand_account)):
    """Show the creator's name, start a deal and the 6-month protection window, and open a chat."""
    campaign = _brand_campaign(body.campaignId, brand)
    creator = col(schema.USERS).find_one({'_id': oid(creator_id)})
    if not creator or role_of(creator) != 'creator' or status_of(creator) != 'active' or not creator.get('verified'):
        raise HTTPException(404, 'Creator not found.')

    existing = col(schema.REVEALS).find_one({'campaignId': str(campaign['_id']), 'creatorAccountId': str(creator['_id'])})
    if existing:
        return {'name': existing['creatorName'], 'handle': existing['creatorHandle'], 'dealId': existing.get('dealId')}

    name, handle = display_name(creator), handle_of(creator)
    started = now()
    budget = int(campaign.get('budget') or 0) // max(1, int(campaign.get('creators') or 1))
    platform = next((p for p in campaign.get('platforms') or [] if p in PLATFORMS), 'instagram')
    brief = campaign.get('brief') or {}
    code = deal_code()
    col(schema.DEALS).insert_one({
        'code': code,
        'campaignId': str(campaign['_id']),
        'brandAccountId': str(brand['_id']),
        'creatorAccountId': str(creator['_id']),
        'campaignName': campaign.get('name', ''),
        'brandName': display_name(brand),
        'creatorName': name,
        'creatorHandle': handle,
        'deliverable': brief.get('contentType') or 'To be agreed',
        'platform': platform,
        'budget': budget,
        'ris': fees_.ris_for_budget(budget),
        'stage': 'selected',
        'deadline': campaign.get('deadline') or '',
        'signedOn': None,
        'submissions': [],
        'revisions': [],
        'flaggedChat': False,
        'updatedAt': iso(),
    })
    col(schema.REVEALS).insert_one({
        'campaignId': str(campaign['_id']),
        'brandAccountId': str(brand['_id']),
        'creatorAccountId': str(creator['_id']),
        'brandName': display_name(brand),
        'creatorName': name,
        'creatorHandle': handle,
        'dealId': code,
        'since': iso(started),
        'until': iso(_add_months(started, fees_.PROTECTION_MONTHS)),
        'status': 'clear',
        'note': 'Protection window started when the brand revealed this creator.',
    })
    open_conversation(brand, creator, campaign.get('name', ''), code)
    notify(creator['_id'], f"{display_name(brand)} picked you for {campaign.get('name', '')}. Open your deals to see it.")
    return {'name': name, 'handle': handle, 'dealId': code}


@router.get('/api/monitor/active')
async def monitored_creators(brand: dict = Depends(brand_account)):
    """Creators this brand revealed, with their 6-month protection window."""
    out = []
    for r in col(schema.REVEALS).find({'brandAccountId': str(brand['_id'])}).sort('since', -1):
        out.append({
            'id': str(r['_id']),
            'name': r.get('creatorName', ''),
            'handle': r.get('creatorHandle', ''),
            'since': r.get('since', ''),
            'until': r.get('until', ''),
            'status': r.get('status', 'clear'),
            'note': r.get('note', ''),
        })
    return out


# ── Scheduled job ────────────────────────────────────────────────────────
@router.get('/cron/deals/auto-approve', dependencies=[Depends(cron_secret)])
async def auto_approve():
    """Content counts as approved when the brand's review window ends without action."""
    approved = 0
    for deal in col(schema.DEALS).find({'stage': 'review'}):
        ends = deal.get('graceEndsOn')
        if ends and parse_iso(ends) <= now():
            _update_deal(deal, {'stage': 'verify', 'approvedAt': iso(), 'autoApproved': True})
            notify(deal['creatorAccountId'], f"Your content for {deal['campaignName']} was approved automatically when the review window ended.")
            notify(deal['brandAccountId'], f"The review window for {deal['campaignName']} ended, so the content counts as approved.")
            approved += 1
    return {'approved': approved}
