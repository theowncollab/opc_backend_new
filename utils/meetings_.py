"""
Rules for "Schedule a meet", shared by the website booking routes and the team console.

- Visitors can only book the day after today, in India time (IST, UTC+5:30).
- Slots are 30 minutes, from 9:00 am to 11:00 pm IST (the last one starts at 10:30 pm).
- The meeting link is not created automatically: the team emails it and marks it sent.
"""
import os
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
SLOT_MINUTES = 30
DAY_START = (9, 0)    # 9:00 am IST
DAY_END = (23, 0)     # 11:00 pm IST (end of the last slot)


def _times() -> list[str]:
    start = DAY_START[0] * 60 + DAY_START[1]
    end = DAY_END[0] * 60 + DAY_END[1]
    return [f'{m // 60:02d}:{m % 60:02d}' for m in range(start, end, SLOT_MINUTES)]


DAY_SLOTS = _times()  # ['09:00', '09:30', ..., '22:30']


def now_ist() -> datetime:
    return datetime.now(timezone.utc).astimezone(IST)


def bookable_date() -> str:
    """The only day a visitor can book: tomorrow in IST, as YYYY-MM-DD."""
    return (now_ist().date() + timedelta(days=1)).isoformat()


def slot_end(time: str) -> str:
    h, m = map(int, time.split(':'))
    total = h * 60 + m + SLOT_MINUTES
    return f'{total // 60:02d}:{total % 60:02d}'


def label(time: str) -> str:
    """'21:30' -> '9:30 pm'."""
    h, m = map(int, time.split(':'))
    return f"{(h % 12) or 12}:{m:02d} {'am' if h < 12 else 'pm'}"


def link_from_email() -> str:
    """The address the team sends meeting links from (shown to the visitor)."""
    return os.getenv('MEET_FROM_EMAIL') or os.getenv('SMTP_USER') or 'support@theowncollab.com'
