"""Platform settings the dashboard reads instead of hard-coding them."""
from fastapi import APIRouter

from utils import fees_

router = APIRouter()


@router.get('/api/config/fees')
async def get_fees():
    """Fee, grace-period tiers, IIS tiers and the payments switch (same values as the dashboard's fees.ts)."""
    return fees_.as_dict()
