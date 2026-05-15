"""add reservation_id to orders

Step 10 needs the Celery `commit_inventory` task to call
`Inventory.CommitReservation(reservation_id)` long after the HTTP
request that created the order is gone. Persisting the id on the
order row is the simplest durable hand-off: idempotent retries can
look it up, and a stuck order is debuggable from psql alone.

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("reservation_id", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("orders", "reservation_id")
