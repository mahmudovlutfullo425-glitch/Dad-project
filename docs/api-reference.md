# REST API reference (R13)

Comprehensive per-endpoint reference for the flash-sale platform's
HTTP surface. The live OpenAPI 3.1 specification is the canonical
contract — Swagger UI renders it at
[`/docs`](https://159.65.114.240.nip.io/docs) and the raw JSON is
at [`/openapi.json`](https://159.65.114.240.nip.io/openapi.json).
This document is the human-readable companion that the grader (and
viva) can read without running the stack.

**Base URL (production):** `https://159.65.114.240.nip.io/api`
**Base URL (local dev):** `http://localhost/api`

All endpoints below are reachable at `${BASE_URL}${path}` (prepend
`/api` because FastAPI uses `root_path=/api` behind the gateway).

---

## Conventions

- **Auth:** endpoints labelled "Bearer" require an
  `Authorization: Bearer <jwt>` header. Tokens come from
  `POST /auth/login` and expire in 60 min (configurable via
  `JWT_EXPIRY_MINUTES`).
- **Rate-limited:** subject to the token-bucket limiter
  ([ADR 0002](adr/0002-token-bucket-rate-limiter.md)). Exceeded
  buckets return `429 Too Many Requests` with a `Retry-After`
  header and JSON body `{"error":"rate_limited","retry_after":<sec>}`.
- **Pagination:** `?page=<n>&page_size=<n>` (max 100). Response
  includes `total`, `page`, `page_size`, and `items`.
- **Errors:** standard FastAPI envelope `{"detail":<str|list>}` for
  4xx and 5xx. Validation errors give 422 with per-field details.
- **Content type:** request bodies are `application/json` except for
  `POST /auth/login` which uses `application/x-www-form-urlencoded`
  (OAuth2 password-grant compatibility).

---

## Authentication

### `POST /auth/register`

Create a new user account.

**Body:**
```json
{
  "email": "string (RFC-5322)",
  "password": "string (≥ 8 chars)",
  "full_name": "string"
}
```

**Responses:**
- `201 Created` — `UserOut` (see schema below)
- `400 Bad Request` — email already registered
- `422` — validation error

---

### `POST /auth/login`

Form-data login (OAuth2 password grant). Rate-limited by
`LOGIN_PER_IP` (5 burst, then 1/20s).

**Body (form-encoded):**
```
username=<email>&password=<password>
```

**Responses:**
- `200 OK` — `{"access_token": "<jwt>", "token_type": "bearer", "expires_in": 3600}`
- `401 Unauthorized` — wrong credentials
- `429 Too Many Requests` — rate limit exceeded

---

### `GET /auth/me`

Return the authenticated user's profile.

**Auth:** Bearer
**Responses:**
- `200 OK` — `UserOut`
- `401 Unauthorized` — missing / invalid / expired token

---

## Products & catalogue

### `GET /products`

Browse the catalogue with optional filters.

**Query params:**
- `page` (int, default 1)
- `page_size` (int, default 20, max 100)
- `category_slug` (str, optional)
- `brand` (str, optional)
- `min_price` / `max_price` (decimal, optional)
- `is_active` (bool, default true)

**Responses:**
- `200 OK` — `ProductList` (`{items: ProductOut[], total, page, page_size}`)

---

### `GET /products/{id}`

Single product detail with variants and category. **Cached** —
served from Redis `hot:product:{id}` with 300 s TTL when
`PRODUCT_CACHE_ENABLED=true` (default).

**Responses:**
- `200 OK` — `ProductOut`
- `404 Not Found` — no product with that id

---

### `POST /products`

Create a product. Triggers a Meilisearch index update.

**Auth:** Admin (Bearer + `is_admin=true`)
**Body:** `ProductCreate`
**Responses:**
- `201 Created` — `ProductOut`
- `403 Forbidden` — not admin
- `422` — validation error

---

### `PATCH /products/{id}`

Partial update. Triggers a Meilisearch reindex of this product.

**Auth:** Admin
**Body:** `ProductUpdate` (any subset of fields)
**Responses:**
- `200 OK` — `ProductOut`
- `404` — not found

---

### `DELETE /products/{id}`

**Soft delete** — sets `is_active = false`. Removes from
Meilisearch index.

**Auth:** Admin
**Responses:**
- `204 No Content`
- `404` — not found

---

### `GET /categories`

List all categories as a flat array (parent_id-linked for
client-side tree assembly).

**Responses:**
- `200 OK` — `CategoryOut[]`

---

## Search

### `GET /search/products`

Typo-tolerant + faceted search backed by Meilisearch. R6
measurements show 2.7× lower p50 vs Postgres ILIKE
(see `docs/measurements/README.md`).

**Query params:**
- `q` (str, required)
- `category_slug` / `brand` / `min_price` / `max_price` (filters)
- `in_stock_only` (bool)
- `sort` (one of: `price:asc`, `price:desc`, `created_at:desc`)
- `limit` (int, default 20, max 100)
- `offset` (int, default 0)

**Responses:**
- `200 OK` — `SearchResponse` (`{hits, total, took_ms, facets}`)

---

## Cart (Redis-backed)

The cart hash lives at `cart:{user_id}` in Redis with a 7-day TTL
that extends on every read. The Postgres `carts` table is the
durable record for analytics; the live working copy is in Redis.

### `GET /cart`

Return the user's current cart, joining variant details from
Postgres.

**Auth:** Bearer
**Responses:**
- `200 OK` — `CartOut` (`{items, subtotal, item_count}`)

---

### `POST /cart/items`

Add a variant to the cart, or increment its quantity if already
present.

**Auth:** Bearer
**Body:** `{"variant_id": <int>, "quantity": <int ≥ 1>}`
**Responses:**
- `200 OK` — updated `CartOut`
- `404` — variant doesn't exist

---

### `PATCH /cart/items/{variant_id}`

Set the exact quantity for a variant. Removes from cart if
`quantity == 0`.

**Auth:** Bearer
**Body:** `{"quantity": <int ≥ 0>}`
**Responses:**
- `200 OK` — updated `CartOut`

---

### `DELETE /cart/items/{variant_id}`

Remove a single variant from the cart.

**Auth:** Bearer
**Responses:**
- `200 OK` — updated `CartOut`

---

### `DELETE /cart`

Clear the entire cart.

**Auth:** Bearer
**Responses:**
- `204 No Content`

---

## Checkout & orders

### `POST /checkout`

Convert the user's Redis cart into a durable Order. **Rate-limited**
by `CHECKOUT_GLOBAL` (1000 burst, 200/s sustained).

Flow:
1. Read cart from Redis
2. Validate `address_id` belongs to user
3. Call `inventory.ReserveStock` via gRPC with idempotency_key
4. INSERT `orders` (status=`pending`), `payments` (status=`initiated`)
5. Enqueue Celery `process_order(order_id)` chain
6. Clear Redis cart
7. Return `OrderOut`

**Auth:** Bearer
**Body:** `{"address_id": <int>, "payment_method": "card"|"cod"}`
**Responses:**
- `200 OK` — `OrderOut` (status will be `pending`; the async chain
  flips it to `paid → fulfilling` within seconds)
- `400 Bad Request` — cart empty / invalid address / insufficient
  stock
- `429 Too Many Requests` — global rate limit hit

---

### `GET /orders`

Paginated list of the user's orders, newest first.

**Auth:** Bearer
**Query params:** `page`, `page_size`
**Responses:**
- `200 OK` — `OrderList`

---

### `GET /orders/{id}`

Single order detail with line items and payment status.

**Auth:** Bearer (must own the order, OR be admin)
**Responses:**
- `200 OK` — `OrderOut`
- `403 Forbidden` — not the owner and not admin
- `404` — order doesn't exist

---

## Flash sales

### `GET /flashsales`

List active and upcoming flash sales.

**Query params:**
- `status` (optional, default `active,scheduled` if omitted)

**Responses:**
- `200 OK` — `FlashSaleOut[]`

---

### `GET /flashsales/{id}`

Detail of one flash sale with its `flash_sale_items` and prices.

**Responses:**
- `200 OK` — `FlashSaleOut`
- `404` — not found

---

### `POST /flashsales/{id}/buy`

The hot-path fast-buy endpoint. **Rate-limited** by
`FLASH_BUY_PER_USER` (3 burst, then 1/10s).

Flow (also drawn in `docs/bpmn/flashsale-buy.bpmn`):
1. Rate-limit check → 429 if exceeded
2. Time-window check (`now BETWEEN starts_at AND ends_at`) → 400
3. Per-user purchase counter check via Redis INCR → 400 if cap
4. `inventory.ReserveStock` → 409 if out of stock
5. Persist Order + Payment in Postgres
6. Enqueue fulfilment chain
7. Emit ClickHouse `flash_sale_event` with action=`accepted`
8. Return `OrderOut`

**Auth:** Bearer
**Body:** `{"variant_id": <int>, "quantity": <int ≥ 1>}`
**Responses:**
- `200 OK` — `OrderOut`
- `400 Bad Request` — sale not active / over per-user limit
- `409 Conflict` — insufficient stock
- `429 Too Many Requests` — per-user rate limit exceeded

---

## Admin analytics (ClickHouse-backed)

### `GET /admin/analytics/flashsales/{id}`

Per-sale rollup pulled from ClickHouse's
`flash_sale_minute_stats` materialised view.

**Auth:** Admin
**Responses:**
- `200 OK` — `{ sale_id, total_attempts, accepted, rejected,
  rate_limited, by_minute: [...]}`

---

### `GET /admin/analytics/orders/daily?days=N`

Daily revenue + order count + status breakdown for the last N days
(default 30, max 90).

**Auth:** Admin
**Responses:**
- `200 OK` — `[{date, count, total_revenue, by_status}, ...]`

---

## Health & ops

### `GET /health`

Liveness probe for the gateway / load balancer. No body parsing,
no DB access — fastest possible response.

**Responses:**
- `200 OK` — `{"status": "ok"}`

---

## Pydantic schemas (referenced above)

### `UserOut`
```json
{
  "id": 1,
  "email": "user1@ecom.local",
  "full_name": "Test User 1",
  "is_admin": false,
  "created_at": "2026-02-15T12:34:56Z"
}
```

### `ProductOut`
```json
{
  "id": 42,
  "name": "Acme Widget Pro",
  "slug": "acme-widget-pro",
  "description": "...",
  "brand": "Acme",
  "base_price": "99.00",
  "is_active": true,
  "category": {"id": 3, "name": "Widgets", "slug": "widgets"},
  "variants": [
    {"id": 100, "sku": "AWP-S", "variant_name": "Small",
     "price": "99.00", "weight_grams": 500}
  ]
}
```

### `CartOut`
```json
{
  "items": [
    {"variant_id": 100, "sku": "AWP-S", "name": "Acme Widget Pro (Small)",
     "quantity": 2, "unit_price": "99.00", "line_total": "198.00"}
  ],
  "subtotal": "198.00",
  "item_count": 2
}
```

### `OrderOut`
```json
{
  "id": 12345,
  "user_id": 1,
  "address_id": 3,
  "status": "pending",
  "subtotal": "198.00",
  "shipping_fee": "5.00",
  "total": "203.00",
  "flash_sale_id": null,
  "placed_at": "2026-05-17T18:30:00Z",
  "items": [
    {"variant_id": 100, "quantity": 2, "unit_price": "99.00", "line_total": "198.00"}
  ],
  "payment": {"id": 99, "status": "initiated", "amount": "203.00", "currency": "USD"}
}
```

### `SearchResponse`
```json
{
  "hits": [
    {"id": 42, "name": "...", "slug": "...", "brand": "Acme",
     "price": 99.00, "category_name": "Widgets", "in_stock": true}
  ],
  "total": 137,
  "took_ms": 8,
  "facets": {
    "brand": {"Acme": 12, "Globex": 7},
    "category_name": {"Widgets": 137},
    "in_stock": {"true": 130, "false": 7}
  }
}
```

### `FlashSaleOut`
```json
{
  "id": 1,
  "name": "Spring Mega Sale",
  "starts_at": "2026-05-17T13:00:00Z",
  "ends_at": "2026-05-17T16:00:00Z",
  "status": "active",
  "items": [
    {"id": 10, "variant_id": 200, "sale_price": "59.40",
     "quantity_allocated": 50, "per_user_limit": 2,
     "variant": {"sku": "WGT-RED", "name": "Widget (Red)",
                 "product_id": 42, "product_name": "Widget"}}
  ]
}
```

---

## HTTP status codes used

| Code | Meaning in this API |
|---|---|
| 200 | Success, body returned |
| 201 | Resource created, body returned |
| 204 | Success, no body |
| 400 | Bad request — domain validation failed (cart empty, sale ended, etc.) |
| 401 | Unauthenticated — missing / invalid / expired JWT |
| 403 | Forbidden — authenticated but lacks permission (non-admin on admin route) |
| 404 | Resource not found |
| 409 | Conflict — most commonly insufficient stock during `ReserveStock` |
| 422 | Request body failed Pydantic validation (per-field errors in `detail`) |
| 429 | Rate limit exceeded — includes `Retry-After` header |
| 500 | Server error — check OTel trace ID in response headers |

---

## Tracing & observability

Every request gets a trace ID injected by the OTel middleware,
visible in:

- Response header: `X-Trace-Id: <hex>`
- Server logs (Loki)
- Tempo trace UI (`http://<droplet>:3001` → Explore → Tempo)

For a request that crosses services (e.g., `/api/flashsales/X/buy`
calls `inventory.ReserveStock` via gRPC), the trace shows the full
api → inventory span tree in one place.
