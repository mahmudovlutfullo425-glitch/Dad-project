"""gRPC servicer implementing the four inventory RPCs.

Design summary:

- **CheckStock** — pure Redis read, sub-millisecond. Returns per-item
  availability plus an ``all_available`` rollup so callers don't have
  to fold the list themselves.
- **ReserveStock** — dispatched on ``USE_POSTGRES_STOCK``:

  - *Redis mode (default, production):* single Lua script call (loaded
    once, then EVALSHA). The script does idempotency, multi-variant
    pre-check, and multi-variant DECRBY in one atomic step. The
    reservation hash records the idempotency key so Release can clean
    both at once.
  - *Postgres mode (R6 measurement baseline):* ``SELECT ... FOR UPDATE``
    on ``inventory_levels`` rows in sorted variant order (to avoid
    deadlocks), check ``quantity_on_hand - quantity_reserved >= qty``
    for each, then ``UPDATE quantity_reserved += qty``. The reservation
    hash is still written to Redis — same shape as Redis mode plus a
    ``pg=1`` marker — so Commit / Release route to the right backend.

- **CommitReservation** — reads the reservation hash. ``pg=1`` →
  Postgres path decrements both ``quantity_on_hand`` and
  ``quantity_reserved``. Otherwise (Redis mode) only ``quantity_on_hand``
  is decremented; the Redis counter was already debited at reserve time.
  Missing reservation = idempotent success (already committed / released).
- **ReleaseReservation** — symmetric: ``pg=1`` → ``UPDATE
  quantity_reserved -= qty``; Redis mode → ``INCRBY stock:{vid}`` back.

The two modes share the reservation-tracking layout deliberately so
the api / flashsales caller path is identical in both modes. Switching
``USE_POSTGRES_STOCK`` only changes where the hot decrement happens;
the surrounding lifecycle stays the same.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select, update

import inventory_pb2 as pb
import inventory_pb2_grpc as pb_grpc

from app.config import get_settings
from app.db import AsyncSessionLocal
from app.lua_scripts import RESERVE_STOCK_LUA
from app.models import InventoryLevel
from app.observability import STOCK_DECREMENT_LATENCY, get_tracer
from app.redis_client import get_redis

# Module-level tracer for the manual spans below. The OTel SDK
# returns a NoopTracer if `setup_telemetry` hasn't run, so this is
# safe to call at import time.
_tracer = get_tracer()


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
        restarted since we last SCRIPT LOAD'd, we reload and retry.

        Wrapped in a manual span + a histogram observation so the
        flash-sale Grafana dashboard can chart the decrement latency
        distribution end-to-end."""
        await self._ensure_script_loaded(redis)
        # Histogram .time() observes elapsed seconds on exit even when
        # the body raises — important so failed reserves still show
        # up in the latency panel rather than masking a slow path.
        with STOCK_DECREMENT_LATENCY.time():
            with _tracer.start_as_current_span("inventory.reserve_lua") as span:
                span.set_attribute("ratelimit.idem_key", idem_key)
                span.set_attribute("inventory.items", (len(argv) - 4) // 2)
                try:
                    return await redis.evalsha(
                        self._reserve_sha, 1, idem_key, *argv
                    )
                except Exception as exc:  # redis-py wraps errors variably
                    if "NOSCRIPT" not in str(exc).upper():
                        raise
                    span.add_event("noscript_reload")
                    self._reserve_sha = await redis.script_load(RESERVE_STOCK_LUA)
                    return await redis.evalsha(
                        self._reserve_sha, 1, idem_key, *argv
                    )

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

        # Settings re-read per call — cheap (cached behind @lru_cache)
        # and lets the load-test runner flip USE_POSTGRES_STOCK between
        # runs without recreating the servicer.
        if get_settings().use_postgres_stock:
            return await self._reserve_postgres(request)
        return await self._reserve_redis(request)

    async def _reserve_redis(self, request):
        """Atomic Redis-Lua reservation (production path)."""
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

    async def _reserve_postgres(self, request):
        """SELECT ... FOR UPDATE reservation (R6 baseline path).

        Acquires row locks on ``inventory_levels`` rows in **sorted**
        variant_id order so two concurrent reservations touching an
        overlapping set of variants cannot deadlock against each
        other. Inside the lock window we check
        ``quantity_on_hand - quantity_reserved >= qty`` and, if all
        items pass, bump ``quantity_reserved`` for each."""
        redis = await get_redis()

        ttl = request.ttl_seconds if request.ttl_seconds > 0 else 300
        idem_ttl = max(ttl * 2, 600)
        idem_key = f"idem:reserve:{request.idempotency_key}"

        new_id = str(uuid.uuid4())
        # SET NX gives us atomic "claim the idempotency key OR observe
        # an existing reservation". Race losers fall into the GET branch
        # below and return the winner's reservation_id without doing a
        # second Postgres reservation.
        acquired = await redis.set(idem_key, new_id, nx=True, ex=idem_ttl)
        if not acquired:
            existing = await redis.get(idem_key)
            return pb.ReserveStockResponse(
                success=True, reservation_id=_decode(existing)
            )

        # Coalesce duplicate variant_ids (defensive — protobuf doesn't
        # forbid them) and lock in sorted order to dodge deadlocks.
        wanted: dict[int, int] = {}
        for item in request.items:
            wanted[item.variant_id] = wanted.get(item.variant_id, 0) + item.quantity
        variant_ids = sorted(wanted.keys())

        with STOCK_DECREMENT_LATENCY.time():
            with _tracer.start_as_current_span("inventory.reserve_postgres") as span:
                span.set_attribute("ratelimit.idem_key", idem_key)
                span.set_attribute("inventory.items", len(variant_ids))
                try:
                    async with AsyncSessionLocal() as session:
                        async with session.begin():
                            stmt = (
                                select(InventoryLevel)
                                .where(InventoryLevel.variant_id.in_(variant_ids))
                                .order_by(InventoryLevel.variant_id)
                                .with_for_update()
                            )
                            rows = (await session.scalars(stmt)).all()
                            by_id = {r.variant_id: r for r in rows}

                            # Pre-check every variant before any mutation
                            # so a partial reservation never escapes the
                            # transaction. Rolls back automatically on
                            # the raise (session.begin() context).
                            for vid in variant_ids:
                                row = by_id.get(vid)
                                if row is None:
                                    await redis.delete(idem_key)
                                    return pb.ReserveStockResponse(
                                        success=False,
                                        rejected=[
                                            pb.StockItem(variant_id=vid, quantity=0)
                                        ],
                                        error=f"insufficient:{vid}",
                                    )
                                free = row.quantity_on_hand - row.quantity_reserved
                                if free < wanted[vid]:
                                    await redis.delete(idem_key)
                                    return pb.ReserveStockResponse(
                                        success=False,
                                        rejected=[
                                            pb.StockItem(variant_id=vid, quantity=0)
                                        ],
                                        error=f"insufficient:{vid}",
                                    )

                            # All checks pass — commit the increments.
                            for vid in variant_ids:
                                await session.execute(
                                    update(InventoryLevel)
                                    .where(InventoryLevel.variant_id == vid)
                                    .values(
                                        quantity_reserved=(
                                            InventoryLevel.quantity_reserved
                                            + wanted[vid]
                                        )
                                    )
                                )
                except Exception:
                    # Pool timeout / deadlock-detected / etc. Release the
                    # idempotency claim so a retry can try again instead
                    # of getting a stale reservation_id pointing nowhere.
                    await redis.delete(idem_key)
                    raise

        # Mirror the Redis-mode reservation hash so Commit/Release can
        # use the same lookup. ``pg=1`` flips them into the Postgres
        # branch.
        res_key = f"reservation:{new_id}"
        hset_payload = {
            "user_id": str(request.user_id),
            "idem_key": idem_key,
            "pg": "1",
        }
        for vid, qty in wanted.items():
            hset_payload[f"v_{vid}"] = str(qty)
        await redis.hset(res_key, mapping=hset_payload)
        await redis.expire(res_key, ttl)

        return pb.ReserveStockResponse(success=True, reservation_id=new_id)

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
        is_postgres = False
        for k, v in items_hash.items():
            if k.startswith("v_"):
                try:
                    variant_qtys[int(k[2:])] = int(v)
                except ValueError:
                    continue
            elif k == "idem_key":
                idem_key = v
            elif k == "pg" and v == "1":
                is_postgres = True

        if not variant_qtys:
            await redis.delete(res_key)
            if idem_key:
                await redis.delete(idem_key)
            return pb.CommitResponse(success=True)

        async with AsyncSessionLocal() as session:
            if is_postgres:
                # Reserve already pre-debited quantity_reserved durably.
                # Commit moves the debit from "reserved" to "on hand
                # consumed" — i.e. decrement both columns.
                for vid, qty in variant_qtys.items():
                    await session.execute(
                        update(InventoryLevel)
                        .where(InventoryLevel.variant_id == vid)
                        .values(
                            quantity_on_hand=InventoryLevel.quantity_on_hand - qty,
                            quantity_reserved=InventoryLevel.quantity_reserved - qty,
                        )
                    )
            else:
                # Redis mode: stock counter was decremented in-memory at
                # reserve time, but quantity_on_hand is still the
                # pre-sale value. Reconcile it now.
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
        is_postgres = False
        for k, v in items_hash.items():
            if k.startswith("v_"):
                try:
                    variant_qtys[int(k[2:])] = int(v)
                except ValueError:
                    continue
            elif k == "idem_key":
                idem_key = v
            elif k == "pg" and v == "1":
                is_postgres = True

        if is_postgres:
            # Roll the reservation back inside Postgres — the durable
            # quantity_reserved bump from _reserve_postgres goes away.
            async with AsyncSessionLocal() as session:
                for vid, qty in variant_qtys.items():
                    await session.execute(
                        update(InventoryLevel)
                        .where(InventoryLevel.variant_id == vid)
                        .values(
                            quantity_reserved=InventoryLevel.quantity_reserved - qty
                        )
                    )
                await session.commit()
        else:
            # Redis mode: just bump the in-memory counters back.
            for vid, qty in variant_qtys.items():
                await redis.incrby(f"stock:{vid}", qty)

        await redis.delete(res_key)
        if idem_key:
            await redis.delete(idem_key)

        return pb.ReleaseResponse(success=True)
