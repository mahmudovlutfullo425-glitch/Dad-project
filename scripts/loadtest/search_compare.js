// R6 measurement #2 — catalogue search latency, naive Postgres ILIKE
// vs Meilisearch.
//
// Runs two k6 scenarios *back-to-back* in a single process, so the
// summary JSON contains both p50/p95/p99 numbers for direct comparison.
// The k6 startTime gates ensure they don't overlap — running them in
// parallel would have them competing for the same Postgres connection
// pool and gateway worker slots, polluting both measurements.
//
//   make k6-search-compare
//
// Tunables via env:
//   BASE_URL  default http://gateway
//   QUERY     default "acme"   (one of the seeded brand names; case-insensitive)
//   VUS       default 100
//   DURATION  default 60s

import http from 'k6/http';
import { check } from 'k6';
import { Trend } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://gateway';
const QUERY = __ENV.QUERY || 'acme';
const VUS = parseInt(__ENV.VUS || '100', 10);
const DURATION = __ENV.DURATION || '60s';

const ilikeLatency = new Trend('search_postgres_ilike_ms', true);
const meiliLatency = new Trend('search_meilisearch_ms', true);

export const options = {
    scenarios: {
        ilike: {
            executor: 'constant-vus',
            vus: VUS,
            duration: DURATION,
            exec: 'ilikeScenario',
            gracefulStop: '5s',
            tags: { variant: 'postgres_ilike' },
        },
        // startTime offset matches DURATION so they run sequentially —
        // do NOT change to 0 unless you also halve the VUs, otherwise
        // both scenarios will contend for the same Postgres pool and
        // the ILIKE numbers will skew artificially high.
        meilisearch: {
            executor: 'constant-vus',
            vus: VUS,
            duration: DURATION,
            startTime: DURATION,
            exec: 'meiliScenario',
            gracefulStop: '5s',
            tags: { variant: 'meilisearch' },
        },
    },
    thresholds: {
        http_req_failed: ['rate<0.01'],
    },
};

export function ilikeScenario() {
    const res = http.get(
        `${BASE_URL}/api/products?name_like=${encodeURIComponent(QUERY)}&page_size=20`,
        { tags: { endpoint: 'search_ilike' } }
    );
    ilikeLatency.add(res.timings.duration);
    check(res, {
        'ILIKE status 200': (r) => r.status === 200,
    });
}

export function meiliScenario() {
    const res = http.get(
        `${BASE_URL}/api/search/products?q=${encodeURIComponent(QUERY)}&limit=20`,
        { tags: { endpoint: 'search_meili' } }
    );
    meiliLatency.add(res.timings.duration);
    check(res, {
        'Meilisearch status 200': (r) => r.status === 200,
    });
}
