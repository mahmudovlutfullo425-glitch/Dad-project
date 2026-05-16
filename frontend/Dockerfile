# syntax=docker/dockerfile:1.7

# ---------- Stage 1: install + build ----------
# Merged deliberately. Splitting deps and builder used to be common
# (faster cache invalidation), but `COPY --from=deps node_modules` is
# brittle across stages — the npm-managed symlinks under
# node_modules/.bin/ don't always survive the copy, which surfaces as
# `sh: next: not found` at build time. Single-stage install + build
# keeps the symlinks intact. The BuildKit cache mount on /root/.npm
# still gives us most of the rebuild-speed win.
FROM node:20-alpine AS builder
WORKDIR /app

# Step 1: install deps. Cache mount keeps tarballs across builds so
# only the first build pays the full download cost (~2 min on a
# warm connection); rebuilds finish the install in 10-30 s.
#
# NPM_STRICT_SSL: default true (verify TLS, what you want in
# production). Set to "false" via --build-arg when building behind a
# corporate proxy that does TLS inspection (Fortinet / Zscaler /
# Cisco Umbrella) — Windows trusts the corporate CA but Alpine
# doesn't, so npm would otherwise silently fail to fetch tarballs.
# Tarballs are still SHA-512 integrity-checked from package-lock.json,
# so disabling strict-ssl drops the TLS layer but not the package
# integrity layer.
#
# Usage:
#   docker compose build frontend                                  # strict TLS (clean network)
#   docker compose build --build-arg NPM_STRICT_SSL=false frontend # behind corporate proxy
ARG NPM_STRICT_SSL=true
COPY package.json package-lock.json* ./
RUN --mount=type=cache,target=/root/.npm,sharing=locked \
    if [ "$NPM_STRICT_SSL" = "false" ]; then \
        echo ">>> Disabling npm strict-ssl (corporate proxy mode)"; \
        npm config set strict-ssl false; \
    fi && \
    if [ -f package-lock.json ]; then \
        npm ci --prefer-offline --no-audit --no-fund; \
    else \
        npm install --prefer-offline --no-audit --no-fund; \
    fi

# Step 2: build. NEXT_PUBLIC_API_URL is baked into the browser bundle
# at this point — override at image-build time with `--build-arg`.
COPY . .
ARG NEXT_PUBLIC_API_URL=/api
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
RUN npm run build

# ---------- Stage 2: runtime ----------
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
# Non-root user. Next.js standalone output runs fine as nobody;
# uid 1001 keeps file permissions readable.
RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs
# Pull only the standalone bundle — strips dev deps automatically.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public
USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
