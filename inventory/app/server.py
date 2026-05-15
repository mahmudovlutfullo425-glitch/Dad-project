"""Inventory service gRPC server entrypoint.

Boot sequence:

1. Open the shared async Redis client (and fail fast if unreachable).
2. Bootstrap ``stock:{variant_id}`` counters from the durable
   ``inventory_levels`` table. A SET-NX lock guards against two
   replicas racing during the same restart.
3. Start the asyncio gRPC server, register reflection, listen on
   the configured port.
4. Wait for SIGINT/SIGTERM, then drain (server.stop with grace), and
   close Redis + Postgres pools.
"""
from __future__ import annotations

import asyncio
import signal

import grpc
from grpc_reflection.v1alpha import reflection
from sqlalchemy import select

import inventory_pb2 as pb
import inventory_pb2_grpc as pb_grpc

from app.config import get_settings
from app.db import AsyncSessionLocal, engine
from app.models import InventoryLevel
from app.observability import setup_telemetry
from app.ratelimit.interceptor import RateLimitInterceptor
from app.ratelimit.redis_backend import RedisBucketStore
from app.redis_client import close_redis, get_redis, init_redis
from app.service import InventoryServicer

BOOTSTRAP_LOCK_KEY = "lock:inventory_bootstrap"
BOOTSTRAP_LOCK_TTL = 60  # seconds — long enough for the loader, short enough to recover


async def bootstrap_stock_counters() -> None:
    """Load quantity_on_hand from Postgres into Redis ``stock:`` keys.

    Idempotent under concurrent restarts: the SET NX lock means only
    one replica writes the counters on a given boot. Whichever loses
    the race trusts the winner."""
    redis = await get_redis()

    acquired = await redis.set(
        BOOTSTRAP_LOCK_KEY, "1", nx=True, ex=BOOTSTRAP_LOCK_TTL
    )
    if not acquired:
        print("Bootstrap lock held by another replica — skipping.", flush=True)
        return

    try:
        async with AsyncSessionLocal() as session:
            stmt = select(InventoryLevel)
            levels = (await session.scalars(stmt)).all()

        if not levels:
            print("No inventory_levels rows found — counters left at zero.", flush=True)
            return

        # MSET in a single round trip. quantity_reserved is subtracted
        # so we restart with "what's actually free" rather than total.
        mapping = {
            f"stock:{lv.variant_id}": str(
                max(0, lv.quantity_on_hand - lv.quantity_reserved)
            )
            for lv in levels
        }
        await redis.mset(mapping)
        print(f"Bootstrapped {len(mapping)} stock counters into Redis.", flush=True)
    finally:
        # Release the lock immediately on success; on crash it expires
        # naturally after BOOTSTRAP_LOCK_TTL seconds.
        await redis.delete(BOOTSTRAP_LOCK_KEY)


async def serve() -> None:
    settings = get_settings()

    # Bring up tracing + the Prometheus sidecar BEFORE we open Redis
    # or create the gRPC server, so the bootstrap step (which hits
    # Postgres and Redis) is itself traced and visible end-to-end.
    setup_telemetry(service_name="inventory")

    await init_redis()
    await bootstrap_stock_counters()

    # The interceptor uses the same Redis client as the rest of the
    # service (DB 0, shared with api). A separate bucket store wraps
    # it so rate-limit ops stay isolated from inventory mutations.
    bucket_store = RedisBucketStore(await get_redis())

    server = grpc.aio.server(interceptors=[RateLimitInterceptor(bucket_store)])
    pb_grpc.add_InventoryServicer_to_server(InventoryServicer(), server)

    # Server reflection — lets `grpcurl` and `grpc_cli` introspect
    # the service without needing the .proto. Handy for the viva demo.
    service_names = (
        pb.DESCRIPTOR.services_by_name["Inventory"].full_name,
        reflection.SERVICE_NAME,
    )
    reflection.enable_server_reflection(service_names, server)

    listen_addr = f"[::]:{settings.inventory_grpc_port}"
    server.add_insecure_port(listen_addr)

    await server.start()
    print(f"Inventory gRPC server listening on {listen_addr}", flush=True)

    shutdown = asyncio.Event()

    def _signal_handler():
        shutdown.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler in asyncio.
            pass

    await shutdown.wait()
    print("Shutdown signal received — draining...", flush=True)
    await server.stop(grace=5)
    await close_redis()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(serve())
