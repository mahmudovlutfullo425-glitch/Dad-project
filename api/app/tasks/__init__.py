"""Celery task modules.

- :mod:`app.tasks.order` — the 5-step order-fulfilment chain plus
  the ``process_order`` dispatch helper used by checkout and
  flash-sale buy endpoints.
- :mod:`app.tasks.scheduled` — beat-driven housekeeping jobs.
"""
