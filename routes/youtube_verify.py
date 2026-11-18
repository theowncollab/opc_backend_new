"""
YouTube verification: a one-time check with Google.

1. In the dashboard, the person clicks "Verify with YouTube". Google's popup asks
   them to let OPC see their YouTube account (read-only, the youtube.readonly scope).
2. The browser sends the short-lived access token Google gives it to this endpoint.
3. We check the token was issued to OPC's own Google client (GOOGLE_CLIENT_ID) and
   includes the YouTube permission, so a token made for another app is refused.
4. We read the channel it belongs to (name, handle, subscribers), save it as
   verified, and then revoke the token. Nothing from Google is kept except that snapshot.

Re-verifying later repeats the same steps and refreshes the numbers.
"""
import os

import requests
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from database import schema
from routes.social_verify import _replace_social, _socials_out
from utils.deps_ import creator_or_brand
from utils.helpers_ import audit, col, display_name, iso

router = APIRouter()

YOUTUBE_SCOPE = 'https://www.googleapis.com/auth/youtube.readonly'
TOKENINFO_URL = 'https://oauth2.googleapis.com/tokeninfo'
CHANNELS_URL = 'https://www.googleapis.com/youtube/v3/channels'
REVOKE_URL = 'https://oauth2.googleapis.com/revoke'
TIMEOUT = 6  # seconds per call; Vercel's free tier stops a request after 10


class YouTubeBody(BaseModel):
    access_token: str = Field(min_length=10, max_length=4096)


def _check_token(token: str) -> None:
    """The token must be live, made for OPC's Google client, and include the YouTube permission."""
    client_id = os.getenv('GOOGLE_CLIENT_ID', '').strip()
    if not client_id:
        raise HTTPException(503, 'YouTube verification isn’t set up yet. Try again later.')
    try:
        res = requests.get(TOKENINFO_URL, params={'access_token': token}, timeout=TIMEOUT)
    except requests.RequestException:
        raise HTTPException(502, 'We couldn’t reach Google. Try again in a minute.')
    if res.status_code != 200:
        raise HTTPException(400, 'Google didn’t accept that sign-in. Try again.')
    info = res.json()
    if client_id not in (info.get('aud'), info.get('azp')):
        raise HTTPException(400, 'Google didn’t accept that sign-in. Try again.')
    if YOUTUBE_SCOPE not in (info.get('scope') or '').split():
        raise HTTPException(400, 'OPC needs permission to see your YouTube account. Try again and tick the YouTube box.')


def _read_channel(token: str) -> dict:
    try:
        res = requests.get(CHANNELS_URL, params={'part': 'snippet,statistics', 'mine': 'true'},
                           headers={'Authorization': f'Bearer {token}'}, timeout=TIMEOUT)
    except requests.RequestException:
        raise HTTPException(502, 'We couldn’t reach YouTube. Try again in a minute.')
    if res.status_code == 403:
        # Usually the daily YouTube API allowance is used up.
        raise HTTPException(503, 'YouTube checks are busy right now. Try again later today.')
    if res.status_code != 200:
        raise HTTPException(400, 'YouTube didn’t accept that sign-in. Try again.')
    items = res.json().get('items') or []
    if not items:
        raise HTTPException(422, 'This Google account doesn’t have a YouTube channel. Sign in with the account that owns your channel.')
    return items[0]


def _revoke(token: str) -> None:
    """Best effort: we're done with the token, so tell Google to cancel it."""
    try:
        requests.post(REVOKE_URL, data={'token': token}, timeout=TIMEOUT)
    except requests.RequestException:
        pass


@router.post('/api/users/me/socials/youtube')
def verify_youtube(body: YouTubeBody, account: dict = Depends(creator_or_brand)):
    """Verify the YouTube channel behind a one-time Google access token. Returns the socials list."""
    token = body.access_token.strip()
    try:
        _check_token(token)
        channel = _read_channel(token)
    finally:
        _revoke(token)

    channel_id = channel.get('id')
    snippet = channel.get('snippet') or {}
    stats = channel.get('statistics') or {}
    title = (snippet.get('title') or 'YouTube channel').strip()
    handle = (snippet.get('customUrl') or '').strip() or title
    hidden = bool(stats.get('hiddenSubscriberCount'))
    subscribers = 0 if hidden else int(stats.get('subscriberCount') or 0)

    # One channel, one OPC person. The same person's creator and brand accounts may share it.
    taken = col(schema.USERS).find_one({
        '_id': {'$ne': account['_id']},
        'email': {'$ne': account.get('email')},
        'socials': {'$elemMatch': {'platform': 'youtube', 'channelId': channel_id, 'verified': True}},
    })
    if taken:
        raise HTTPException(409, 'This YouTube channel is already verified on another OPC account. Contact support@theowncollab.com if it’s yours.')

    _replace_social(account, {
        'platform': 'youtube',
        'handle': handle,
        'followers': subscribers,
        'verified': True,
        'pending': False,
        'verifiedOn': iso()[:10],
        'via': 'google',
        'channelId': channel_id,
        'channelTitle': title,
        'hiddenSubscribers': hidden,
        'videos': int(stats.get('videoCount') or 0),
    })
    audit('System', 'Verified YouTube channel with Google', f'{display_name(account)}: {title} ({handle}), {subscribers} subscribers')
    return {'socials': _socials_out(account['_id'])}
