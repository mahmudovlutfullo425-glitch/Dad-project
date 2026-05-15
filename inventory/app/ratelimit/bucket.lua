-- Atomic token-bucket refill+consume — the correctness core of R11.
--
-- Loaded into Redis once per process via SCRIPT LOAD, then invoked
-- with EVALSHA on every rate-limited request. The whole script runs
-- inside one Redis command, so the refill, the threshold check, and
-- the decrement cannot race against a concurrent caller hitting the
-- same bucket key.
--
-- Inputs:
--   KEYS[1]   = bucket key (e.g. "bucket:flash_buy_per_user:42")
--   ARGV[1]   = capacity            (int)
--   ARGV[2]   = refill_rate         (tokens per second, float)
--   ARGV[3]   = now                 (unix seconds, float)
--   ARGV[4]   = requested           (tokens to consume, int)
--
-- Returns: {allowed, remaining, retry_after_ms}
--   allowed         = 1 on success, 0 on rejection
--   remaining       = integer tokens left (floor)
--   retry_after_ms  = ms until `requested` tokens become available
--                     (0 on success; ceiling of the wait on rejection)
--
-- The retry_after is returned in milliseconds because Redis Lua
-- truncates floats on the wire — millisecond ints preserve enough
-- precision to surface as a useful `Retry-After` header.

local capacity     = tonumber(ARGV[1])
local refill_rate  = tonumber(ARGV[2])
local now          = tonumber(ARGV[3])
local requested    = tonumber(ARGV[4])

local data = redis.call('HMGET', KEYS[1], 'tokens', 'last_refill')
local tokens       = tonumber(data[1])
local last_refill  = tonumber(data[2])

-- First time we see this key — start with a full bucket.
if tokens == nil then
    tokens = capacity
    last_refill = now
end

-- Clock skew protection: if the caller's clock went backwards
-- relative to last_refill (rare, but possible across replicas),
-- treat the gap as zero. We never *refund* tokens.
local elapsed = math.max(0, now - last_refill)
tokens = math.min(capacity, tokens + elapsed * refill_rate)

local allowed = 0
local retry_after_ms = 0

if tokens >= requested then
    tokens = tokens - requested
    allowed = 1
else
    if refill_rate > 0 then
        retry_after_ms = math.ceil(((requested - tokens) / refill_rate) * 1000)
    else
        -- Disabled bucket (refill_rate == 0): tell the caller to never retry.
        retry_after_ms = 2147483647
    end
end

-- Persist state. Strings preserve more precision than letting Redis
-- coerce a Lua number through its default formatter.
redis.call('HSET', KEYS[1], 'tokens', tostring(tokens), 'last_refill', tostring(now))
-- 1-hour idle expiry so abandoned buckets don't linger in Redis.
-- Any subsequent request resets it.
redis.call('EXPIRE', KEYS[1], 3600)

return {allowed, math.floor(tokens), retry_after_ms}
