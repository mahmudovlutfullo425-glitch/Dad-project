"""Synchronous gRPC client for Celery tasks.

The Celery worker runs sync code; using `grpc.aio` here would force
each task to spin up an event loop just to make one RPC. The sync
channel is cheap, pools internally, and survives the worker
process lifetime.

The stub is lazily constructed because import-time channel creation
would race the inventory service on cold start of the compose stack.
"""
from __future__ import annotations

import threading

import grpc

import inventory_pb2_grpc as pb_grpc

from app.config import get_settings

_lock = threading.Lock()
_channel: grpc.Channel | None = None
_stub: pb_grpc.InventoryStub | None = None


def get_sync_inventory_stub() -> pb_grpc.InventoryStub:
    global _channel, _stub
    if _stub is not None:
        return _stub
    with _lock:
        if _stub is not None:
            return _stub
        s = get_settings()
        target = f"{s.inventory_host}:{s.inventory_grpc_port}"
        # Same options as the async channel — keepalive lets us survive
        # the inventory service's container restarts without surfacing
        # UNAVAILABLE on the very next call.
        _channel = grpc.insecure_channel(
            target,
            options=[
                ("grpc.keepalive_time_ms", 30_000),
                ("grpc.keepalive_timeout_ms", 10_000),
            ],
        )
        _stub = pb_grpc.InventoryStub(_channel)
    return _stub


def close_sync_inventory_stub() -> None:
    global _channel, _stub
    with _lock:
        if _channel is not None:
            _channel.close()
        _channel = None
        _stub = None
