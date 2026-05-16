// R6 measurement #1 — product-detail latency with and without the
// Redis hot cache.
//
// The endpoint and code path are identical between runs; the
// differentiator is the api service's PRODUCT_CACHE_ENABLED env flag.
// Pass --tag mode=baseline / --tag mode=cached when running so the
// summary JSONs are self-labelling.
//
//   # Baseline (no cache; restart api with PRODUCT_CACHE_ENABLED=false)
//   make k6-product-detail-baseline
//
//   # Cached (default config)
//   make k6-product-detail-cached
//
// Tunables via env:
//   BASE_URL        default http://gateway   (compose-internal hostname)
//   PRODUCT_MIN_ID  default 1                (seed has 1..1000)
//   PRODUCT_MAX_ID  default 1000
//   VUS             default 100
//   DURATION        default 60s

import http from 'k6/http';
import { check } from 'k6';
import { Trend } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://gateway';
const MIN_ID = parseInt(__ENV.PRODUCT_MIN_ID || '1', 10);
const MAX_ID = parseInt(__ENV.PRODUCT_MAX_ID || '1000', 10);
const VUS = parseInt(__ENV.VUS || '100', 10);
const DURATION = __ENV.DURATION || '60s';

// A custom trend so the report can pull p50/p95/p99 of THIS endpoint
// specifically, not bucketed with any setup-phase requests.
const productLatency = new Trend('product_detail_latency_ms', true);

export const options = {
    scenarios: {
        product_detail: {
            executor: 'constant-vus',
            vus: VUS,
            duration: DURATION,
            gracefulStop: '5s',
        },
    },
    // Thresholds are *advisory* — k6 still emits results even when
    // they fail; they just colour the summary red so degradations
    // jump out in CI.
    thresholds: {
        http_req_failed: ['rate<0.01'],
        product_detail_latency_ms: ['p(95)<500', 'p(99)<1000'],
    },
};

function randomId() {
    // Math.random is fine — we don't need crypto here, just spread
    // the load across the 1..1000 catalog rows.
    return Math.floor(Math.random() * (MAX_ID - MIN_ID + 1)) + MIN_ID;
}

export default function () {
    const id = randomId();
    const res = http.get(`${BASE_URL}/api/products/${id}`, {
        tags: { endpoint: 'product_detail' },
    });
    productLatency.add(res.timings.duration);
    check(res, {
        'status is 200 or 404': (r) => r.status === 200 || r.status === 404,
    });
}
