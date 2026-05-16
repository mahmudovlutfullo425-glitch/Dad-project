"""Address endpoints — read-only listing of the user's saved addresses.

The frontend checkout page uses this to populate the address picker
so the customer can pick a non-default shipping destination. CRUD on
addresses is out of scope for the academic project (seed data
provides 1–2 per user, which is enough for the demo flows).
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import get_current_user
from app.models import Address, User
from app.schemas.address import AddressOut

router = APIRouter(tags=["addresses"])


@router.get(
    "/addresses",
    response_model=list[AddressOut],
    summary="List the authenticated user's saved addresses",
)
async def list_addresses(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AddressOut]:
    """Default address first, then by id for stable ordering."""
    stmt = (
        select(Address)
        .where(Address.user_id == user.id)
        .order_by(Address.is_default.desc(), Address.id)
    )
    rows = (await db.scalars(stmt)).all()
    return [AddressOut.model_validate(a) for a in rows]
