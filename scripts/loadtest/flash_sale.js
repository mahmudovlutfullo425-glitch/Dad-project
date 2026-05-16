// R6 measurement #3 — flash-sale buy throughput under the two stock
// backends.
//
// Same endpoint and same handler in both runs; what changes between
// runs is the inventory service's USE_POSTGRES_STOCK env flag.
//
//   make loadtest-flashsale        # one-off: refresh the sale window
//   make k6-flash-sale-redis       # baseline: atomic Lua DECRBY
//   make k6-flash-sale-postgres    # alternative: SELECT ... FOR UPDATE
//
// Prereqs (the Make target handles them):
//   1. `make seed` has run (creates user1..user9, password "user1234").
//   2. `make loadtest-flashsale` has run (creates an active sale and
//      lifts per_user_limit + stock to test-friendly headroom).
//   3. `RATE_LIMIT_ENABLED=false` set on api + inventory, services
//      restarted — otherwise FLASH_BUY_PER_USER (capacity 3) bottoms
//      out and the test measures rate-limit rejections, not the
//      stock backend.
//
// Tunables via env:
//   BASE_URL        default http://gateway
//   FLASH_SALE_ID   default 2     (id printed by create_loadtest_flashsale.py)
//   VARIANT_IDS     default 1,2,3,4,5   (comma-separated)
//   USER_COUNT      default 9     (seed creates user1..user9)
//   USER_PASSWORD   default user1234
//   VUS             default 500
//   DURATION        default 30s

import http from 'k6/http';
import { check, fail } from 'k6';
import { Trend, Counter } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://gateway';
const FLASH_SALE_ID = parseInt(__ENV.FLASH_SALE_ID || '2', 10);
const VARIANT_IDS = (__ENV.VARIANT_IDS || '1,2,3,4,5')
    .split(',')
    .map((s) => parseInt(s.trim(), 10))
    .filter((n) => Number.isFinite(n));
const USER_COUNT = parseInt(__ENV.USER_COUNT || '9', 10);
const USER_PASSWORD = __ENV.USER_PASSWORD || 'user1234';
const VUS = parseInt(__ENV.VUS || '500', 10);
const DURATION = __ENV.DURATION || '30s';

const buyLatency = new Trend('flash_sale_buy_latency_ms', true);
const accepted = new Counter('flash_sale_accepted_total');
const rejected_409 = new Counter('flash_sale_stock_insufficient_total');
const rejected_429 = new Counter('flash_sale_rate_limited_total');
const rejected_4xx = new Counter('flash_sale_other_4xx_total');
const rejected_5xx = new Counter('flash_sale_5xx_total');

export const options = {
    scenarios: {
        flash_sale: {
            executor: 'constant-vus',
            vus: VUS,
            duration: DURATION,
            gracefulStop: '10s',
        },
    },
    thresholds: {
        // No http_req_failed threshold here — 4xx during a flash sale
        // is expected (stock-insufficient, per-user-limit). We track
        // the breakdown via the custom counters above instead.
        flash_sale_buy_latency_ms: ['p(95)<2000'],
    },
};

// setup() runs once before any VU starts. Returns whatever JSON we
// put here — gets passed to every default() call as the first arg.
export function setup() {
    const tokens = [];
    for (let i = 1; i <= USER_COUNT; i++) {
        const email = `user${i}@ecom.local`;
        // OAuth2 login uses form-encoded "username" + "password" fields.
        const res = http.post(
            `${BASE_URL}/api/auth/login`,
            { username: email, password: USER_PASSWORD },
            {
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                tags: { phase: 'setup' },
            }
        );
        if (res.status !== 200) {
            fail(
                `login failed for ${email}: status=${res.status} body=${res.body}`
            );
        }
        const body = res.json();
        tokens.push(body.access_token);
    }
    console.log(`Logged in ${tokens.length} users for flash-sale load test.`);
    console.log(
        `Targeting flash_sale_id=${FLASH_SALE_ID} variants=[${VARIANT_IDS.join(',')}]`
    );
    return { tokens };
}

export default function (data) {
    // Round-robin tokens by VU index plus a per-iter jitter, so a
    // single user doesn't monopolise the bucket counter if the rate
    // limiter is left on.
    const idx = (__VU + __ITER) % data.tokens.length;
    const token = data.tokens[idx];
    const variantId = VARIANT_IDS[Math.floor(Math.random() * VARIANT_IDS.length)];

    const res = http.post(
        `${BASE_URL}/api/flashsales/${FLASH_SALE_ID}/buy`,
        JSON.stringify({ variant_id: variantId, quantity: 1 }),
        {
            headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${token}`,
            },
            tags: { endpoint: 'flash_sale_buy' },
        }
    );

    buyLatency.add(res.timings.duration);

    if (res.status === 201) {
        accepted.add(1);
    } else if (res.status === 409) {
        rejected_409.add(1);
    } else if (res.status === 429) {
        rejected_429.add(1);
    } else if (res.status >= 400 && res.status < 500) {
        rejected_4xx.add(1);
    } else if (res.status >= 500) {
        rejected_5xx.add(1);
    }

    // The "ok" envelope: anything in 2xx is a happy path; 409/429 are
    // expected back-pressure signals (not bugs). 5xx means the
    // backend cracked under load — that IS a failure for this test.
    check(res, {
        'status is 2xx or expected 4xx': (r) =>
            r.status < 500 && (r.status < 400 || r.status === 409 || r.status === 429),
    });
}
