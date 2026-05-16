# FlashShop frontend — Next.js 14 storefront + admin (Step 15)

Single-tier customer + admin UI for the Flash-Sale E-commerce project.
Consumes the FastAPI backend through the Nginx gateway at `/api/*` from
the browser and directly at `http://api:8000` from React Server
Components running inside the same compose network.

## Stack

- **Next.js 14.2** (App Router) with `output: standalone` for a slim
  runtime image (~150 MB).
- **TypeScript 5.6** in strict mode.
- **Tailwind CSS 3.4** + `@tailwindcss/forms` for the design system —
  no shadcn / Material / vendored component lib.
- **SWR 2.2** for client-side data fetching (cart, orders, admin
  tables that need refresh).
- **jose 5** to decode the JWT client-side (no verification — that's
  the api's job; we just need to read `exp` and skip stale tokens).

## Auth

- Login posts form-encoded credentials to `/api/auth/login`
  (matches the OAuth2PasswordRequestForm flow on the api side).
- The returned JWT is written to `localStorage["jwt"]` and attached as
  a `Authorization: Bearer ...` header on every subsequent request.
- `is_admin` is **not** in the JWT — `AuthProvider` fetches
  `/api/auth/me` once after login and caches the result. Admin
  revocation works without re-issuing tokens.
- localStorage is XSS-readable, which is documented as a known
  limitation. For production a Next.js BFF cookie path would be the
  next hardening step (out of scope here).

## Pages

| Path | Render mode | Notes |
|---|---|---|
| `/` | RSC | Featured products + soonest-ending flash sale banner |
| `/products` | RSC | Catalogue with category/brand/price filters |
| `/products/[id]` | RSC | Detail with variant list and Add-to-cart |
| `/search` | client | Meilisearch facets (category, brand) |
| `/cart` | client | Live cart with stepper + remove |
| `/checkout` | client | Address picker → POST /checkout |
| `/orders` | client | Polls every 5 s to follow Celery status |
| `/orders/[id]` | client | Polls every 3 s while non-terminal |
| `/flashsales/[id]` | mixed | RSC for header, client countdown + buy |
| `/auth/login` | client | Form-encoded login |
| `/auth/register` | client | JSON register, auto-login |
| `/admin` | client | Landing tiles + guard |
| `/admin/orders` | client | All-orders table, status filter, polls every 10 s |
| `/admin/inventory` | client | Stock-level table, low-stock toggle |
| `/admin/analytics` | client | Flash-sale ClickHouse stats |

The `/products/[id]` URL takes a numeric id rather than the slug the
roadmap suggested — the backend's canonical lookup is by id, and
adding a slug-resolution endpoint wasn't worth the extra round trip.
Documented spec divergence.

## Endpoints this app consumes

All under `/api/*` from the browser, `http://api:8000/*` from server
components. Auth required unless noted.

- `POST /auth/register`, `POST /auth/login`, `GET /auth/me`
- `GET /products` (incl. `name_like`, paging, filters)
- `GET /products/{id}` (cached when `PRODUCT_CACHE_ENABLED=true`)
- `GET /categories`
- `GET /search/products` (anonymous; Meilisearch-backed, facets)
- `GET /cart`, `POST /cart/items`, `PATCH /cart/items/{vid}`,
  `DELETE /cart/items/{vid}`, `DELETE /cart`
- `POST /checkout`
- `GET /orders`, `GET /orders/{id}`
- `GET /addresses` (added in step 15)
- `GET /flashsales`, `GET /flashsales/{id}`, `POST /flashsales/{id}/buy`
- `GET /admin/orders`, `GET /admin/inventory` (added in step 15)
- `GET /admin/analytics/flashsales/{id}`

## Error handling

- **429** — `lib/api.ts` reads `Retry-After`, surfaces a typed
  `ApiError`. The flash-sale buy button shows a toast: "Slow down —
  try again in {N}s". Login does the same for credential-stuffing
  rate-limit hits.
- **409** — surfaced inline as "Sorry, sold out before we got to your
  order" on the buy / checkout buttons.
- **401** — `lib/api.ts` calls `clearToken()` and fires an
  `auth:changed` event. `AuthProvider` re-reads, the user falls back
  to the unauthenticated state, and the page protects itself.
- **5xx** — surfaced via the global `app/error.tsx` boundary.

## Build & run

```bash
# Via the compose stack (default — frontend now starts automatically).
make up

# Or just the frontend image.
make frontend-build

# Local hot-reload dev server (faster than docker rebuild).
make frontend-dev
```

The Dockerfile is multi-stage: builder (node:20-alpine, `npm ci` +
`npm run build`) → runner (node:20-alpine, copies `.next/standalone`
and runs `node server.js` as a non-root user).

`NEXT_PUBLIC_API_URL` is **baked into the bundle at build time** (it's
a `NEXT_PUBLIC_*` variable, embedded by Next.js at compile). To point
the browser at a different gateway, rebuild the image with a new build
arg.

`INTERNAL_API_URL` is read at runtime by `lib/server-fetch.ts` and
used only by React Server Components. Default `http://api:8000`.

## Out of scope (documented for the report)

- SSR-time auth (auth state lives in client components; RSC pages are
  always anonymous reads).
- Image upload / product-create / address-CRUD admin UI.
- Realtime via SSE / WebSocket — we poll instead (3 s for an active
  order, 5 s for the orders list, 10 s for admin orders).
- i18n — English only.
- Slug-based product URLs.
