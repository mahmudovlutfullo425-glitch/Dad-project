"""gRPC servicer implementing the four inventory RPCs.

Design summary:

- **CheckStock** — pure Redis read, sub-millisecond. Returns per-item
  availability plus an ``all_available`` rollup so callers don't have
  to fold the list themselves.
- **ReserveStock** — single Lua script call (loaded once, then
  EVALSHA). The script does idempotency, multi-variant pre-check, and
  multi-variant DECRBY in one atomic step. The reservation hash also
  records its idempotency key so Release can clean both at once.
- **CommitReservation** — looks up the reservation hash, applies the
  decrement durably to ``inventory_levels.quantity_on_hand``, and
  deletes both the reservation and the idempotency record. Missing
  reservation = idempotent success (already committed / released).
- **ReleaseReservation** — INCRBY each variant back to its pre-reserve
  count, then delete reservation + idempotency record.
"""
from __future__ import annotations

import uuid

from sqlalchemy import update

import inventory_pb2 as pb
import inventory_pb2_grpc as pb_grpc

from app.db import AsyncSessionLocal
from app.lua_scripts import RESERVE_STOCK_LUA
from app.models import InventoryLevel
from app.redis_client import get_redis


def _decode(value) -> str:
    """Lua replies arrive as bytes from some redis-py versions even
    with decode_responses=True (the response is a multi-bulk array
    that doesn't get auto-decoded). Be defensive."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


class InventoryServicer(pb_grpc.InventoryServicer):
    def __init__(self) -> None:
        self._reserve_sha: str | None = None

    async def _ensure_script_loaded(self, redis) -> None:
        if self._reserve_sha is None:
            self._reserve_sha = await redis.script_load(RESERVE_STOCK_LUA)

    async def _eval_reserve(self, redis, idem_key: str, argv: list[str]):
        """EVALSHA with a NOSCRIPT-resilient fallback. If Redis was
        restarted since we last SCRIPT LOAD'd, we reload and retry."""
        await self._ensure_script_loaded(redis)
        try:
            return await redis.evalsha(self._reserve_sha, 1, idem_key, *argv)
        except Exception as exc:  # redis-py wraps server errors variably
            if "NOSCRIPT" not in str(exc).upper():
                raise
            self._reserve_sha = await redis.script_load(RESERVE_STOCK_LUA)
            return await redis.evalsha(self._reserve_sha, 1, idem_key, *argv)

    # ---------- RPC methods ----------

    async def CheckStock(self, request, context):
        redis = await get_redis()
        available: list[pb.StockItem] = []
        missing: list[pb.StockItem] = []
        all_available = True

        for item in request.items:
            raw = await redis.get(f"stock:{item.variant_id}")
            current = int(raw) if raw is not None else 0
            if current >= item.quantity:
                available.append(
                    pb.StockItem(variant_id=item.variant_id, quantity=current)
                )
            else:
                missing.append(
                    pb.StockItem(
                        variant_id=item.variant_id,
                        quantity=item.quantity - current,
                    )
                )
                all_available = False

        return pb.CheckStockResponse(
            all_available=all_available,
            available=available,
            missing=missing,
        )

    async def ReserveStock(self, request, context):
        if not request.idempotency_key:
            return pb.ReserveStockResponse(success=False, error="idempotency_key required")
        if not request.items:
            return pb.ReserveStockResponse(success=False, error="items required")

        redis = await get_redis()
        new_id = str(uuid.uuid4())
        # Caller can specify a TTL; clamp to a sane default if missing.
        ttl = request.ttl_seconds if request.ttl_seconds > 0 else 300
        # Idempotency outlives the reservation so retries within the
        # window after a release still get the original id (or a
        # `not found` if it's been committed).
        idem_ttl = max(ttl * 2, 600)
        idem_key = f"idem:reserve:{request.idempotency_key}"

        argv: list[str] = [new_id, str(request.user_id), str(ttl), str(idem_ttl)]
        for item in request.items:
            argv.append(str(item.variant_id))
            argv.append(str(item.quantity))

        result = await self._eval_reserve(redis, idem_key, argv)

        success = int(result[0]) == 1
        ret_id = _decode(result[1])
        error = _decode(result[2])

        if not success:
            rejected: list[pb.StockItem] = []
            if error.startswith("insufficient:"):
                try:
                    vid = int(error.split(":", 1)[1])
                    rejected.append(pb.StockItem(variant_id=vid, quantity=0))
                except ValueError:
                    pass
            return pb.ReserveStockResponse(
                success=False, rejected=rejected, error=error
            )

        return pb.ReserveStockResponse(success=True, reservation_id=ret_id)

    async def CommitReservation(self, request, context):
        if not request.reservation_id:
            return pb.CommitResponse(success=False, error="reservation_id required")

        redis = await get_redis()
        res_key = f"reservation:{request.reservation_id}"
        items_hash: dict[str, str] = await redis.hgetall(res_key)

        if not items_hash:
            # Already committed or released — treat as success so the
            # caller's retry loop terminates.
            return pb.CommitResponse(success=True)

        variant_qtys: dict[int, int] = {}
        idem_key: str | None = None
        for k, v in items_hash.items():
            if k.startswith("v_"):
                try:
                    variant_qtys[int(k[2:])] = int(v)
                except ValueError:
                    continue
            elif k == "idem_key":
                idem_key = v

        if not variant_qtys:
            await redis.delete(res_key)
            if idem_key:
                await redis.delete(idem_key)
            return pb.CommitResponse(success=True)

        async with AsyncSessionLocal() as session:
            for vid, qty in variant_qtys.items():
                await session.execute(
                    update(InventoryLevel)
                    .where(InventoryLevel.variant_id == vid)
                    .values(quantity_on_hand=InventoryLevel.quantity_on_hand - qty)
                )
            await session.commit()

        await redis.delete(res_key)
        if idem_key:
            await redis.delete(idem_key)

        return pb.CommitResponse(success=True)

    async def ReleaseReservation(self, request, context):
        if not request.reservation_id:
            return pb.ReleaseResponse(success=False)

        redis = await get_redis()
        res_key = f"reservation:{request.reservation_id}"
        items_hash: dict[str, str] = await redis.hgetall(res_key)

        if not items_hash:
            return pb.ReleaseResponse(success=True)

        variant_qtys: dict[int, int] = {}
        idem_key: str | None = None
        for k, v in items_hash.items():
            if k.startswith("v_"):
                try:
                    variant_qtys[int(k[2:])] = int(v)
                except ValueError:
                    continue
            elif k == "idem_key":
                idem_key = v

        # Refund Redis counters.
        for vid, qty in variant_qtys.items():
            await redis.incrby(f"stock:{vid}", qty)

        await redis.delete(res_key)
        if idem_key:
            await redis.delete(idem_key)

        return pb.ReleaseResponse(success=True)
