"""
OPC money rules. Mirrors dashboard-app/src/config/fees.ts and is served by
GET /api/config/fees so the dashboard, contracts and this API never disagree.
TODO(business): confirm with your CA before payments go live.
"""
PLATFORM_FEE = 0.05

GRACE_TIERS = {
    'low': {'label': 'Low risk', 'risRange': [0, 35], 'holdDays': 3, 'holdShare': 0.15},
    'medium': {'label': 'Medium risk', 'risRange': [36, 65], 'holdDays': 5, 'holdShare': 0.20},
    'high': {'label': 'High risk', 'risRange': [66, 100], 'holdDays': 7, 'holdShare': 0.25},
}

IIS_TIERS = [
    {'name': 'Rising Star', 'min': 0, 'max': 39},
    {'name': 'Established', 'min': 40, 'max': 64},
    {'name': 'Pro Creator', 'min': 65, 'max': 84},
    {'name': 'Elite', 'min': 85, 'max': 100},
]

PROTECTION_MONTHS = 6
PAYMENTS_LIVE = False  # matches PAYMENTS_LIVE in the dashboard


def tier_for_ris(ris: int) -> str:
    if ris <= 35:
        return 'low'
    if ris <= 65:
        return 'medium'
    return 'high'


def ris_for_budget(budget: int) -> int:
    """Until RIS has real inputs, estimate it from the budget bands in the brand agreement."""
    if budget < 20000:
        return 30
    if budget < 70000:
        return 50
    return 75


def split_budget(budget: int, tier: str) -> dict:
    fee = round(budget * PLATFORM_FEE)
    hold = round(budget * GRACE_TIERS[tier]['holdShare'])
    return {'fee': fee, 'hold': hold, 'immediate': budget - fee - hold}


def as_dict() -> dict:
    return {
        'platformFee': PLATFORM_FEE,
        'graceTiers': GRACE_TIERS,
        'iisTiers': IIS_TIERS,
        'protectionMonths': PROTECTION_MONTHS,
        'paymentsLive': PAYMENTS_LIVE,
    }
