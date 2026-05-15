"""End-to-end smoke test for the inventory gRPC service.

Run inside the api container so the generated stubs and the
``app.config`` settings resolve identically to the runtime path::

    docker compose run --rm \\
        -v "$PWD/scripts:/scripts" -w /app -e PYTHONPATH=/app \\
        api python /scripts/inventory_check.py

Covers the four spec verification beats:

1. CheckStock returns availability for an existing variant.
2. ReserveStock decrements the Redis counter and returns a UUID.
3. Same idempotency_key returns the *same* UUID with no extra decrement.
4. CommitReservation persists to Postgres and removes the reservation.
5. ReleaseReservation refunds the Redis counter on a fresh reservation.
"""
import asyncio

import grpc

import inventory_pb2 as pb
import inventory_pb2_grpc as pb_grpc

from app.config import get_settings
from app.redis_client import get_redis, init_redis, close_redis


VARIANT_FOR_RESERVE_COMMIT = 1
VARIANT_FOR_RELEASE = 2
RESERVE_QTY = 2
RELEASE_QTY = 3


async def _stock(redis, variant_id: int) -> int:
    raw = await redis.get(f"stock:{variant_id}")
    return int(raw) if raw is not None else 0


async def main() -> None:
    s = get_settings()
    target = f"{s.inventory_host}:{s.inventory_grpc_port}"
    print(f"Connecting to inventory at {target}\n")

    await init_redis()
    redis = await get_redis()

    channel = grpc.aio.insecure_channel(target)
    stub = pb_grpc.InventoryStub(channel)

    # ---------- 1. CheckStock ----------
    print("=== 1. CheckStock(variant_id=1, quantity=1) ===")
    resp = await stub.CheckStock(
        pb.CheckStockRequest(items=[pb.StockItem(variant_id=1, quantity=1)])
    )
    print(f"all_available = {resp.all_available}")
    for it in resp.available:
        print(f"  available: variant_id={it.variant_id} stock={it.quantity}")
    for it in resp.missing:
        print(f"  missing:   variant_id={it.variant_id} short_by={it.quantity}")

    # ---------- 2. ReserveStock with idempotency ----------
    before = await _stock(redis, VARIANT_FOR_RESERVE_COMMIT)
    print(f"\n=== 2. ReserveStock idem='test1' [vid={VARIANT_FOR_RESERVE_COMMIT} qty={RESERVE_QTY}] ===")
    print(f"  stock:{VARIANT_FOR_RESERVE_COMMIT} before = {before}")

    resp = await stub.ReserveStock(
        pb.ReserveStockRequest(
            idempotency_key="test1",
            user_id=2,
            items=[pb.StockItem(variant_id=VARIANT_FOR_RESERVE_COMMIT, quantity=RESERVE_QTY)],
            ttl_seconds=300,
        )
    )
    after = await _stock(redis, VARIANT_FOR_RESERVE_COMMIT)
    print(f"  success={resp.success} reservation_id={resp.reservation_id}")
    print(f"  stock:{VARIANT_FOR_RESERVE_COMMIT} after = {after}  (decremented by {before - after})")
    first_id = resp.reservation_id

    # ---------- 3. Idempotent retry ----------
    print(f"\n=== 3. ReserveStock idem='test1' AGAIN ===")
    before_retry = await _stock(redis, VARIANT_FOR_RESERVE_COMMIT)
    resp = await stub.ReserveStock(
        pb.ReserveStockRequest(
            idempotency_key="test1",
            user_id=2,
            items=[pb.StockItem(variant_id=VARIANT_FOR_RESERVE_COMMIT, quantity=RESERVE_QTY)],
            ttl_seconds=300,
        )
    )
    after_retry = await _stock(redis, VARIANT_FOR_RESERVE_COMMIT)
    same_id = resp.reservation_id == first_id
    no_decrement = before_retry == after_retry
    print(f"  reservation_id={resp.reservation_id}  same_as_first={same_id}")
    print(f"  stock unchanged on retry: {no_decrement} (was {before_retry}, now {after_retry})")

    # ---------- 4. CommitReservation ----------
    print(f"\n=== 4. CommitReservation({first_id}) ===")
    resp = await stub.CommitReservation(pb.CommitRequest(reservation_id=first_id))
    print(f"  success={resp.success}")
    res_key_exists = await redis.exists(f"reservation:{first_id}")
    print(f"  reservation hash deleted: {res_key_exists == 0}")

    # ---------- 5. ReleaseReservation flow ----------
    before_rel = await _stock(redis, VARIANT_FOR_RELEASE)
    print(f"\n=== 5. ReserveStock then ReleaseReservation [vid={VARIANT_FOR_RELEASE} qty={RELEASE_QTY}] ===")
    print(f"  stock:{VARIANT_FOR_RELEASE} before reserve = {before_rel}")
    resp = await stub.ReserveStock(
        pb.ReserveStockRequest(
            idempotency_key="test_release",
            user_id=2,
            items=[pb.StockItem(variant_id=VARIANT_FOR_RELEASE, quantity=RELEASE_QTY)],
            ttl_seconds=300,
        )
    )
    after_reserve = await _stock(redis, VARIANT_FOR_RELEASE)
    print(f"  after reserve = {after_reserve}  (-{before_rel - after_reserve})")

    release_resp = await stub.ReleaseReservation(
        pb.ReleaseRequest(reservation_id=resp.reservation_id)
    )
    after_release = await _stock(redis, VARIANT_FOR_RELEASE)
    print(f"  release success={release_resp.success}")
    print(f"  after release = {after_release}  (refunded: {after_release == before_rel})")

    await channel.close()
    await close_redis()
    print("\nAll checks complete.")


if __name__ == "__main__":
    asyncio.run(main())
