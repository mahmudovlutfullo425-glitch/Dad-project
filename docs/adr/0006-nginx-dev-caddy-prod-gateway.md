# ADR 0006 — Nginx (dev) + Caddy (prod) gateway split

- **Status:** Accepted
- **Date:** 2026-05-16
- **Owner:** M1 (Platform Lead)

## Context

The gateway has two distinct jobs depending on environment:

| Environment | Need |
|---|---|
| Local dev | Plain HTTP on `:80`, load balance two api replicas, route `/api/*` to api and `/` to frontend. **No TLS** — developers don't want self-signed cert warnings on every `curl`. |
| Production droplet | Same routing, plus **automatic TLS** from Let's Encrypt for the public hostname, plus HTTP→HTTPS redirect. |

Trying to do both with one config means juggling certbot, nginx
reload hooks, ACME challenge paths, and a self-signed dev cert that
every team member has to trust. That's a lot of moving parts for a
team of five working in parallel.

## Decision

Two gateway services in the same `docker-compose.yml`, gated by
[Docker Compose profiles](https://docs.docker.com/compose/profiles/):

| Service | Image | Profile | Ports | TLS |
|---|---|---|---|---|
| `gateway` | nginx:1.27-alpine | `dev` | `:80` | none |
| `gateway-prod` | caddy:2.8-alpine | `prod` | `:80`, `:443` | Let's Encrypt auto |

`make up` activates the `dev` profile → Nginx runs. `make up-prod`
activates the `prod` profile → Caddy runs. Profiles are mutually
exclusive, so they can never fight for ports 80/443 on the same
host.

Caddy reads `PUBLIC_HOSTNAME` at start (set in `.env` to
`<droplet-ip>.nip.io` for the coursework demo) and requests an
HTTP-01 challenge against it. Cert and ACME account persist in named
volumes (`caddy_data`, `caddy_config`) so a `docker compose down`
doesn't burn the Let's Encrypt rate limit.

## Consequences

**Positive**

- Dev experience is unchanged (`make up` works exactly as before).
- Production deployment is one command (`make up-prod`) and one env
  variable (`PUBLIC_HOSTNAME`) — no certbot scripts, no manual cert
  rotation.
- Cert auto-renews ~30 days before expiry without intervention.
- Both gateway configs are committed to the repo — no "where do I
  put the cert?" question for new contributors.

**Negative**

- Two services to maintain (Nginx config + Caddyfile).
- Profile-aware Makefile targets (`make up` vs `make up-prod`) — one
  more thing for a new contributor to learn.
- The Caddy healthcheck needs an HTTP-only loopback site in the
  Caddyfile so the Docker healthcheck doesn't trip on the auto-HTTPS
  redirect.

## Alternatives considered

- **Nginx + certbot in production.** Adds a sidecar container plus
  cron-driven reload hooks; ~5× more configuration than the Caddy
  equivalent.
- **Traefik.** Equivalent to Caddy on TLS automation but heavier and
  with steeper learning curve.
- **Cloudflare proxy in front.** Off-platform; the spec explicitly
  requires the deployment on a single IaaS VM.
