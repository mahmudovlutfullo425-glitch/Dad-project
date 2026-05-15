"""Inventory gRPC service.

Owns the live ``stock:{variant_id}`` counters in Redis and the
``inventory_levels`` table in Postgres. The hot path (CheckStock,
ReserveStock) is Redis-only; CommitReservation reconciles into
Postgres durable storage.
"""
