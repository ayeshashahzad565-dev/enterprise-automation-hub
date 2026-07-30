# syntax=docker/dockerfile:1
#
# Production image for the Enterprise Automation Hub frontend (Next.js).
#
# Three stages: `deps` installs exact, locked dependencies; `builder`
# runs the production build (requires `output: "standalone"` in
# next.config.ts); `runner` copies only the standalone server output
# (`.next/standalone` + `.next/static` + `public`) into a fresh, minimal
# base — node_modules and the build toolchain never reach the final
# image. Runs as the non-root `node` user Node's own official image
# already provides.
#
# Build:  docker build -t eah-frontend .          (from the frontend/ directory)
# Run:    docker run -p 3000:3000 --env-file .env.local eah-frontend
#
# NEXT_PUBLIC_* variables are baked in at build time (Next.js convention)
# — pass them as build args for a real deployment; the placeholders below
# only satisfy the module-load-time validation in src/lib/supabase/env.ts
# (matching .github/workflows/ci.yml's identical CI-placeholder pattern).
#
# All three `FROM node:20-slim` stages are pinned to a digest (not the
# floating `20-slim` tag) for reproducible builds. Pinned 2026-07-29; bump
# deliberately (`docker pull node:20-slim` + `docker inspect
# --format='{{index .RepoDigests 0}}' node:20-slim`) to pick up new
# base-image security patches — update all three stages together.

FROM node:20-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0 AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci


FROM node:20-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0 AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

ARG NEXT_PUBLIC_SUPABASE_URL=https://build-placeholder.supabase.co
ARG NEXT_PUBLIC_SUPABASE_ANON_KEY=build-placeholder-anon-key
ENV NEXT_PUBLIC_SUPABASE_URL=${NEXT_PUBLIC_SUPABASE_URL} \
    NEXT_PUBLIC_SUPABASE_ANON_KEY=${NEXT_PUBLIC_SUPABASE_ANON_KEY} \
    NEXT_TELEMETRY_DISABLED=1

RUN npm run build


FROM node:20-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0 AS runner
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

COPY --from=builder /app/public ./public
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static

USER node
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD node -e "fetch('http://localhost:3000/api/health').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"

CMD ["node", "server.js"]
