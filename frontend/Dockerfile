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
# All three `FROM node:22-slim` stages are pinned to a digest (not the
# floating `22-slim` tag) for reproducible builds. Pinned 2026-08-12; bump
# deliberately (`docker pull node:22-slim` + `docker inspect
# --format='{{index .RepoDigests 0}}' node:22-slim`) to pick up new
# base-image security patches — update all three stages together.
#
# 22, not 20: @supabase/* declares engines.node >= 22, so `npm ci` in the
# deps stage fails on 20. Keep in step with .github/workflows/*.yml.

FROM node:22-slim@sha256:d649c27dae7ba0137b3cef5dd75baa422c08dc3d9e3fc0c23dfb172dc3cc6436 AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci


FROM node:22-slim@sha256:d649c27dae7ba0137b3cef5dd75baa422c08dc3d9e3fc0c23dfb172dc3cc6436 AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

ARG NEXT_PUBLIC_SUPABASE_URL=https://build-placeholder.supabase.co
ARG NEXT_PUBLIC_SUPABASE_ANON_KEY=build-placeholder-anon-key
ENV NEXT_PUBLIC_SUPABASE_URL=${NEXT_PUBLIC_SUPABASE_URL} \
    NEXT_PUBLIC_SUPABASE_ANON_KEY=${NEXT_PUBLIC_SUPABASE_ANON_KEY} \
    NEXT_TELEMETRY_DISABLED=1

RUN npm run build


FROM node:22-slim@sha256:d649c27dae7ba0137b3cef5dd75baa422c08dc3d9e3fc0c23dfb172dc3cc6436 AS runner
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# The base image bundles npm and corepack, and npm vendors its own copy of
# `tar` — currently 7.5.11, which carries CVE-2026-59873 (gzip-bomb denial
# of service, fixed in 7.5.19). Trivy scans that vendored package.json and
# fails this image on it, even though `tar` appears nowhere in
# package-lock.json and `npm audit` therefore never sees it.
#
# A Next.js standalone build runs on `node server.js` alone: no package
# manager is involved at runtime, and the HEALTHCHECK below is plain
# `node -e`. Removing them drops the vulnerable code from the runtime image
# rather than shipping it unused, and trims the attack surface generally.
RUN rm -rf /usr/local/lib/node_modules/npm \
           /usr/local/lib/node_modules/corepack \
           /usr/local/bin/npm \
           /usr/local/bin/npx \
           /usr/local/bin/corepack

COPY --from=builder /app/public ./public
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static

USER node
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD node -e "fetch('http://localhost:3000/api/health').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"

CMD ["node", "server.js"]
