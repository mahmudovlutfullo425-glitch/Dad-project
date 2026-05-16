# Step 16 — Deployment to a public droplet

This document walks the **full path** from a brand-new DigitalOcean
account to a publicly reachable `https://<your-host>/` running the
flash-sale stack with HTTPS, the storefront, Swagger UI, Grafana, and
all 16 services.

Total time, from droplet creation to passing the verification curl: **~25 minutes**.

> Spec compliance (PROJECT.md §7.3): we must deploy to a real VM, not a
> PaaS (Vercel, Railway, Render, Fly are explicitly banned). DigitalOcean,
> Hetzner, AWS EC2, or any other IaaS provider satisfies the rule.

---

## 1. Provision the droplet (~5 min)

In the DigitalOcean control panel → **Create → Droplets**:

| Setting | Value |
|---|---|
| Image | Ubuntu 24.04 (LTS) x64 |
| Plan → CPU options | Regular (Intel) — Premium Intel works too |
| Size | **8 GB / 4 vCPU / 160 GB SSD** ($48/mo, $0.07/hr) |
| Datacenter | The region nearest to the grader / demo (e.g. SGP1 for Asia) |
| Authentication | SSH key (paste your `~/.ssh/id_ed25519.pub`) |
| Hostname | `ecom-flashsale` |
| Firewall | (skip — we configure UFW on the droplet itself) |

> **Why 8 GB?** Postgres + Redis + Meilisearch + ClickHouse + Tempo +
> Loki + Prometheus + Grafana + 2× api + worker + beat + Caddy +
> Next.js easily eats 4 GB at idle. 4 GB will OOM-kill ClickHouse
> during the k6 demo. The next size up ($48/mo) is worth it for the
> 24h the project is live; destroy the droplet after the viva.

Once it's up, note the **public IPv4 address** — call it `$DROPLET_IP`
from here on (e.g. `134.122.45.10`).

> **Cost discipline:** DO bills by the hour. Snapshot the droplet
> after submission, then destroy it. A snapshot is ~$0.06/GB/month
> instead of $48/mo for a live droplet.

---

## 2. SSH in and bootstrap (~3 min)

```bash
ssh root@$DROPLET_IP
```

(If you see a host-key warning, accept it. If SSH refuses your key,
the most likely cause is you pasted the *private* key into DO instead
of the public one — recreate the droplet.)

On the droplet, install Docker and the host-side tools:

```bash
# Option A — pipe install.sh straight from the repo (no clone yet)
curl -fsSL https://raw.githubusercontent.com/<your-org>/<repo>/main/scripts/deploy/install.sh \
    | bash

# Option B — clone first, then run it
apt-get update && apt-get install -y git
git clone https://github.com/<your-org>/<repo>.git
cd <repo>
bash scripts/deploy/install.sh
```

The script:

- adds Docker's apt repo and installs Engine + Compose v2 + buildx
- installs `make` and `git`
- opens UFW on 22 / 80 / 443 (everything else blocked)
- bumps the file-descriptor limit (ClickHouse and k6 demand it)
- adds the current user to the `docker` group

When it finishes, **log out and back in** so the `docker` group takes
effect — otherwise every `docker` command will need `sudo`.

```bash
exit
ssh root@$DROPLET_IP
```

---

## 3. Clone the repo & configure `.env` (~3 min)

```bash
cd ~
git clone https://github.com/<your-org>/<repo>.git ecommerce-flashsale
cd ecommerce-flashsale
cp .env.example .env
nano .env
```

Edit these values — leave everything else at its dev default:

```bash
# ---- Rotate every secret away from its dev placeholder ----
POSTGRES_PASSWORD=<run: openssl rand -hex 32>
JWT_SECRET=<run: openssl rand -hex 32>
MEILI_MASTER_KEY=<run: openssl rand -hex 32>
CLICKHOUSE_PASSWORD=<run: openssl rand -hex 32>

# ---- Public address (Step 16) ----
# nip.io turns any IP into a hostname (zero DNS setup, free, real TLS):
#   134.122.45.10  →  134.122.45.10.nip.io
PUBLIC_HOSTNAME=<DROPLET_IP>.nip.io
ADMIN_EMAIL=<your real email>          # Let's Encrypt expiry warnings

# ---- Frontend bundle must point at the public URL ----
NEXT_PUBLIC_API_URL=https://<DROPLET_IP>.nip.io/api
```

Quick way to generate strong secrets in one shot (run on the droplet
**before** editing `.env`):

```bash
for v in POSTGRES_PASSWORD JWT_SECRET MEILI_MASTER_KEY CLICKHOUSE_PASSWORD; do
    echo "$v=$(openssl rand -hex 32)"
done
```

Paste the four lines into `.env` over the placeholders.

---

## 4. Seed + boot (~10 min)

```bash
make seed       # alembic migrate + load 1000 products + 10 users
make up-prod    # boot the full stack with Caddy (auto-TLS)
make reindex    # populate Meilisearch from Postgres
```

`make up-prod` is a thin wrapper around
`docker compose --env-file .env --profile prod up -d`. The `prod`
profile activates **gateway-prod (Caddy)** and skips the dev nginx
gateway, so there's no port conflict.

**Watch Caddy obtain its certificate** (the most failure-prone moment):

```bash
docker compose --profile prod logs -f gateway-prod
```

You should see, within ~30 seconds:

```
{"level":"info","msg":"certificate obtained successfully"...}
{"level":"info","msg":"serving initial configuration"}
```

If you instead see ACME challenge failures, the most likely causes are:

| Symptom | Cause | Fix |
|---|---|---|
| "connection refused" on :80 | UFW blocking | `ufw status` → ensure 80/tcp ALLOW |
| "DNS problem: NXDOMAIN" | typo in PUBLIC_HOSTNAME | re-check `<ip>.nip.io` resolves |
| "rate limit exceeded" | too many cert requests this week | wait an hour, or use the staging issuer |

---

## 5. Verify (~2 min)

From the droplet:

```bash
curl -k https://localhost/api/health     # → {"status":"ok"}
curl    https://$PUBLIC_HOSTNAME/api/health
```

From your laptop:

```bash
open https://$PUBLIC_HOSTNAME/             # storefront
open https://$PUBLIC_HOSTNAME/docs         # Swagger UI
```

**From your phone on mobile data** (not WiFi — this proves it's
genuinely public, not just LAN-reachable):

- Open `https://$PUBLIC_HOSTNAME/` — should load the storefront
- Tap the lock icon — should show "Connection is secure"

Round-trip auth and a flash-sale buy:

```bash
TOKEN=$(curl -s -X POST https://$PUBLIC_HOSTNAME/api/auth/login \
    -d 'username=user1@ecom.local&password=user1234' | jq -r .access_token)
curl -H "Authorization: Bearer $TOKEN" https://$PUBLIC_HOSTNAME/api/auth/me
```

---

## 6. Take screenshots for the report

While the stack is live and Grafana is collecting data, place a few
flash-sale orders (Swagger → `POST /flashsales/1/buy`) and grab three
screenshots for §11 of the design report:

1. **Trace view (Tempo):** the gateway → api → inventory → redis span
   tree for one `/flashsales/1/buy` request.
2. **Logs view (Loki):** logs filtered by the `trace_id` from above.
3. **Metric panel (Prometheus):** the rate-limit-rejected counter
   rising during a k6 run.

Grafana on the droplet is at `http://$DROPLET_IP:3001/` — that port
isn't behind Caddy because it's a private operator surface, not part
of the public API. Lock it down with UFW post-demo if leaving the
droplet up.

---

## 7. Ongoing operations

### Logs

```bash
make logs-prod                          # all services, follow
docker compose --profile prod logs -f api gateway-prod
```

### Restart a single service after editing config

```bash
docker compose --profile prod up -d --force-recreate gateway-prod
```

### Rotate a secret

```bash
nano .env                               # change JWT_SECRET, etc.
make restart-prod                       # recreates affected containers
```

### Renew the TLS cert

Caddy renews automatically ~30 days before expiry. To force a renewal
(rarely needed):

```bash
docker compose --profile prod exec gateway-prod caddy reload --config /etc/caddy/Caddyfile
```

### Stop the stack but keep data

```bash
make down-prod                          # keeps named volumes (pg_data, caddy_data, ...)
```

### Wipe everything (post-submission only)

```bash
make clean                              # destroys ALL data volumes
```

---

## 8. Post-submission: don't keep paying

After the viva:

1. **Snapshot** the droplet from the DO control panel ($0.06/GB/month).
2. **Destroy** the live droplet ($48/mo → $0).
3. If you ever need it back: spin up a new droplet, restore from
   the snapshot, point `nip.io` at the new IP (just edit `.env`,
   `make restart-prod`).

---

## Appendix — Why Caddy and not Nginx+certbot?

The dev gateway is Nginx because it's lighter, it's what the spec
references in §10/Step 4, and it doesn't need TLS for local dev.

For prod we swapped to Caddy purely for **operator ergonomics**:

| Concern | Nginx + certbot | Caddy |
|---|---|---|
| Cert acquisition | Run certbot, mount certs into nginx, restart nginx | Automatic on first request to the hostname |
| Cert renewal | Cron job + certbot + nginx reload | Automatic |
| Config | Two files (nginx.conf + certbot scripts) | One Caddyfile |
| Boot time on a fresh droplet | ~5 min (DNS-01 challenge gymnastics or HTTP-01 dance) | ~30 sec |

Both approaches are valid; for a 24-hour coursework deployment the
Caddy path eliminates a class of failure modes that has nothing to do
with what the project is being graded on.

The Nginx config is still in the repo (`gateway/nginx.conf`,
`gateway/conf.d/default.conf`) and is the gateway in dev — so any
viva question about "explain your nginx config" still works.

---

## Appendix — What `--profile prod` activates

Compose profiles let two mutually exclusive gateway implementations
coexist in the same `docker-compose.yml`:

| Profile | Gateway | Ports | TLS |
|---|---|---|---|
| `dev` (`make up`) | Nginx (`gateway`) | 80 | none |
| `prod` (`make up-prod`) | Caddy (`gateway-prod`) | 80 + 443 | Let's Encrypt |

All other services (api, inventory, worker, beat, frontend, db, redis,
meilisearch, clickhouse, nats, otel-collector, tempo, loki, prometheus,
grafana) are profile-less and run in both modes. The profile selects
*only* which gateway binds the public ports.
