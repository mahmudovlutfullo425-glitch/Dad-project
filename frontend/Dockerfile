# syntax=docker/dockerfile:1.7

# ---------- Stage 1: install deps ----------
FROM node:20-alpine AS deps
WORKDIR /app
# Install with npm (lock file optional in dev). Production builds will
# regenerate the lock — fine for an academic deliverable.
COPY package.json package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

# ---------- Stage 2: build the Next.js app ----------
FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Build-time env var the public bundle reads via process.env. Build
# args (--build-arg NEXT_PUBLIC_API_URL=...) override at image-build time.
ARG NEXT_PUBLIC_API_URL=/api
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
RUN npm run build

# ---------- Stage 3: runtime ----------
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
# Add a non-root user. Next.js standalone output runs fine as nobody;
# uid 1001 keeps file permissions readable.
RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs
# Pull in only what we need to run — standalone output bundles its own
# minimal node_modules tree.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public
USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
