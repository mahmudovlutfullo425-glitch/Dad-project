"""Named rate-limit rules.

Each rule's capacity/refill choice is defensible at the viva: pick
whichever combination matches the threat being mitigated.

- **FLASH_BUY_PER_USER** — one user shouldn't be able to grab the
  entire flash-sale allotment. 3-token burst gives a fair shot at
  the launch instant; 0.1 tokens/s = 1 buy attempt every 10s
  afterwards (a person, not a bot script).

- **LOGIN_PER_IP** — credential stuffing protection. 5 attempts
  burst (real users mis-type), then 1 per 20s — slow enough to make
  a brute-force list infeasible without hurting genuine retries.

- **CHECKOUT_GLOBAL** — backpressure on the inventory service.
  1000-token burst so a sudden launch doesn't 429 legitimate
  shoppers; 200/s sustained matches roughly what one inventory
  replica can drain.

- **API_PER_USER_DEFAULT** — generic ceiling on authenticated
  endpoints. 60-token burst / 1 token/s = effectively "no limit
  for humans, hard limit for runaway scripts".
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Scope(str, Enum):
    USER = "user"
    IP = "ip"
    GLOBAL = "global"


@dataclass(frozen=True)
class RateLimitRule:
    name: str
    capacity: int
    refill_rate: float  # tokens per second
    scope: Scope

    def key_for(self, identity: str | None) -> str:
        """Build the Redis bucket key for the given scope identity."""
        if self.scope == Scope.GLOBAL:
            return f"bucket:{self.name}:global"
        return f"bucket:{self.name}:{identity or 'unknown'}"


FLASH_BUY_PER_USER = RateLimitRule(
    name="flash_buy_per_user",
    capacity=3,
    refill_rate=0.1,
    scope=Scope.USER,
)

LOGIN_PER_IP = RateLimitRule(
    name="login_per_ip",
    capacity=5,
    refill_rate=0.05,
    scope=Scope.IP,
)

CHECKOUT_GLOBAL = RateLimitRule(
    name="checkout_global",
    capacity=1000,
    refill_rate=200.0,
    scope=Scope.GLOBAL,
)

API_PER_USER_DEFAULT = RateLimitRule(
    name="api_per_user_default",
    capacity=60,
    refill_rate=1.0,
    scope=Scope.USER,
)


# Lookup table. Callers reference rules by their uppercase identifier
# so the wiring (router decorators, interceptor methods table) reads
# as plain English.
RULES: dict[str, RateLimitRule] = {
    "FLASH_BUY_PER_USER": FLASH_BUY_PER_USER,
    "LOGIN_PER_IP": LOGIN_PER_IP,
    "CHECKOUT_GLOBAL": CHECKOUT_GLOBAL,
    "API_PER_USER_DEFAULT": API_PER_USER_DEFAULT,
}
