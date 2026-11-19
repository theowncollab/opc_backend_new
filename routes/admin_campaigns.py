"""
Campaigns, for the OPC team: every brand's campaign, with pause, resume and close.

  GET  /api/admin/campaigns                 (deals.view)   all campaigns, newest first
  POST /api/admin/campaigns/{id}/pause      (deals.manage) stop new deals for now; brand is told why
  POST /api/admin/campaigns/{id}/resume     (deals.manage) back to the status it had before
  POST /api/admin/campaigns/{id}/close      (deals.manage) end it for good

A paused or closed campaign can't be edited by the brand, and no new creator can be
revealed from it (routes/deals.py). Deals already running carry on as normal.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from database import schema
from utils.deps_ import require
from utils.helpers_ import audit, col, iso, notify, oid

router = APIRouter()

TEAM_HOLD = ('paused', 'closed')


def _actor(member: dict) -> str:
    return member.get('name') or member.get('email', 'OPC team')


def _get(campaign_id: str) -> dict:
    c = col(schema.CAMPAIGNS).find_one({'_id': oid(campaign_id)})
    if not c:
        raise HTTPException(404, 'Campaign not found.')
    return c


def _out(c: dict, deal_counts: dict) -> dict:
    cid = str(c['_id'])
    return {
        'id': cid, 'name': c.get('name', ''), 'brand': c.get('brandName', ''), 'brandId': c.get('brandAccountId', ''),
        'status': c.get('status', 'draft'), 'budget': int(c.get('budget') or 0), 'platforms': c.get('platforms') or [],
        'creators': int(c.get('creators') or 0), 'cirs': int(c.get('cirs') or 0), 'deadline': c.get('deadline') or '',
        'createdAt': c.get('createdAt', ''), 'updatedAt': c.get('updatedAt', ''), 'deals': deal_counts.get(cid, 0),
        'teamReason': c.get('teamReason', ''), 'teamBy': c.get('teamBy', ''), 'teamAt': c.get('teamAt', ''),
    }


def _deal_counts() -> dict:
    counts: dict = {}
    for d in col(schema.DEALS).find({}, {'campaignId': 1}):
        key = str(d.get('campaignId') or '')
        counts[key] = counts.get(key, 0) + 1
    return counts


class TeamReason(BaseModel):
    reason: str = Field(default='', max_length=500)


@router.get('/api/admin/campaigns')
async def list_campaigns(member: dict = Depends(require('deals.view'))):
    counts = _deal_counts()
    campaigns = sorted(col(schema.CAMPAIGNS).find(), key=lambda c: c.get('updatedAt') or c.get('createdAt') or '', reverse=True)
    return [_out(c, counts) for c in campaigns]


@router.post('/api/admin/campaigns/{campaign_id}/pause')
async def pause_campaign(campaign_id: str, body: TeamReason, member: dict = Depends(require('deals.manage'))):
    c = _get(campaign_id)
    if c.get('status') in TEAM_HOLD:
        raise HTTPException(409, f"This campaign is already {c.get('status')}.")
    if not body.reason.strip():
        raise HTTPException(422, 'Say why you’re pausing it. The brand sees this.')
    col(schema.CAMPAIGNS).update_one({'_id': c['_id']}, {'$set': {
        'status': 'paused', 'statusBefore': c.get('status', 'draft'), 'teamReason': body.reason.strip(),
        'teamBy': _actor(member), 'teamAt': iso(), 'updatedAt': iso()}})
    if c.get('brandAccountId'):
        notify(c['brandAccountId'], f"OPC paused your campaign “{c.get('name', '')}”: {body.reason.strip()}")
    audit(_actor(member), 'Paused campaign', f"{c.get('name', '')} ({c.get('brandName', '')}): {body.reason.strip()}")
    return _out(_get(campaign_id), _deal_counts())


@router.post('/api/admin/campaigns/{campaign_id}/resume')
async def resume_campaign(campaign_id: str, member: dict = Depends(require('deals.manage'))):
    c = _get(campaign_id)
    if c.get('status') != 'paused':
        raise HTTPException(409, 'Only a paused campaign can be resumed.')
    back = c.get('statusBefore') or 'matching'
    col(schema.CAMPAIGNS).update_one({'_id': c['_id']}, {'$set': {'status': back, 'updatedAt': iso(), 'teamBy': _actor(member), 'teamAt': iso()},
                                                          '$unset': {'statusBefore': '', 'teamReason': ''}})
    if c.get('brandAccountId'):
        notify(c['brandAccountId'], f"OPC resumed your campaign “{c.get('name', '')}”.")
    audit(_actor(member), 'Resumed campaign', f"{c.get('name', '')} ({c.get('brandName', '')})")
    return _out(_get(campaign_id), _deal_counts())


@router.post('/api/admin/campaigns/{campaign_id}/close')
async def close_campaign(campaign_id: str, body: TeamReason, member: dict = Depends(require('deals.manage'))):
    c = _get(campaign_id)
    if c.get('status') == 'closed':
        raise HTTPException(409, 'This campaign is already closed.')
    if not body.reason.strip():
        raise HTTPException(422, 'Say why you’re closing it. The brand sees this.')
    col(schema.CAMPAIGNS).update_one({'_id': c['_id']}, {'$set': {
        'status': 'closed', 'teamReason': body.reason.strip(), 'teamBy': _actor(member), 'teamAt': iso(), 'updatedAt': iso()},
        '$unset': {'statusBefore': ''}})
    if c.get('brandAccountId'):
        notify(c['brandAccountId'], f"OPC closed your campaign “{c.get('name', '')}”: {body.reason.strip()}")
    audit(_actor(member), 'Closed campaign', f"{c.get('name', '')} ({c.get('brandName', '')}): {body.reason.strip()}")
    return _out(_get(campaign_id), _deal_counts())
