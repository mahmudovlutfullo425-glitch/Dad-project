"""Verify the gRPC RateLimitInterceptor on Inventory.ReserveStock.

FLASH_BUY_PER_USER has capacity=3, refill_rate=0.1 — so the first 3
reserves from one user_id succeed and the 4th is rejected with
gRPC code RESOURCE_EXHAUSTED. Each call uses a *different*
idempotency_key so the inventory service treats them as distinct
requests rather than idempotent retries (which would otherwise
short-circuit before the interceptor counter fires).
"""
import asyncio

import grpc

import inventory_pb2 as pb
import inventory_pb2_grpc as pb_grpc

from app.config import get_settings


async def main() -> None:
    s = get_settings()
    target = f"{s.inventory_host}:{s.inventory_grpc_port}"
    print(f"Hammering ReserveStock at {target} (4 calls, same user, distinct idem keys)\n")

    channel = grpc.aio.insecure_channel(target)
    stub = pb_grpc.InventoryStub(channel)

    USER = 42  # arbitrary fixed user_id so all four calls share a bucket
    for i in range(1, 5):
        try:
            resp = await stub.ReserveStock(
                pb.ReserveStockRequest(
                    idempotency_key=f"rl-test-{i}",
                    user_id=USER,
                    items=[pb.StockItem(variant_id=100, quantity=1)],
                    ttl_seconds=60,
                )
            )
            print(f"call {i}: success={resp.success} reservation_id={resp.reservation_id[:8]}…")
        except grpc.aio.AioRpcError as err:
            print(f"call {i}: gRPC error code={err.code().name}  detail={err.details()}")

    await channel.close()


if __name__ == "__main__":
    asyncio.run(main())
