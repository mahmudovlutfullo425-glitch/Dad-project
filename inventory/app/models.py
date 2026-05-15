"""Minimal SQLAlchemy model for the inventory service.

Only the columns this service reads or writes are declared. The
canonical full schema lives in the api service (api/app/models.py)
and is owned by Alembic migrations there. Keeping a slim local model
here avoids cross-service Python imports.
"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class InventoryLevel(Base):
    __tablename__ = "inventory_levels"

    variant_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    quantity_on_hand: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_reserved: Mapped[int] = mapped_column(Integer, nullable=False)
    # Declared so SQLAlchemy's onupdate hook fires when we issue an
    # UPDATE on quantity_on_hand from CommitReservation.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
