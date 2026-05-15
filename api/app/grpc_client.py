"""Async gRPC client for the inventory service.

The channel is created in the FastAPI lifespan and kept open for the
lifetime of the process. ``grpc.aio.insecure_channel`` is lazy — it
doesn't actually open a TCP connection until the first call — so this
module never blocks startup waiting for the inventory service.

The Step 9 checkout flow and Step 9 flash-sale buy path will pull
the stub via :func:`get_inventory_stub`.
"""
from __future__ import annotations

import grpc

import inventory_pb2_grpc as pb_grpc

from app.config import get_settings

_channel: grpc.aio.Channel | None = None
_stub: pb_grpc.InventoryStub | None = None


async def init_inventory_client() -> None:
    global _channel, _stub
    if _stub is not None:
        return
    s = get_settings()
    target = f"{s.inventory_host}:{s.inventory_grpc_port}"
    _channel = grpc.aio.insecure_channel(target)
    _stub = pb_grpc.InventoryStub(_channel)


async def close_inventory_client() -> None:
    global _channel, _stub
    if _channel is not None:
        await _channel.close()
    _channel = None
    _stub = None


def get_inventory_stub() -> pb_grpc.InventoryStub:
    if _stub is None:
        raise RuntimeError(
            "Inventory client not initialized — was lifespan startup run?"
        )
    return _stub
