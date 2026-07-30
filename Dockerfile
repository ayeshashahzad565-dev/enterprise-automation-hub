# syntax=docker/dockerfile:1
#
# Production image for the Enterprise Automation Hub backend (FastAPI).
#
# Multi-stage: `builder` installs production dependencies into a venv;
# `runtime` copies only that venv plus the application source into a
# fresh, minimal base — the build toolchain, pip cache, and wheel
# artifacts never reach the final image. Runs as a non-root user, with a
# HEALTHCHECK against the liveness probe (app.api.routers.health).
#
# Build:  docker build -t eah-backend .
# Run:    docker run -p 8000:8000 --env-file .env eah-backend
#
# The same image is reused, with a different CMD, for the job system's
# two worker roles (see docker-compose.production.yml's `worker-default`/
# `worker-escalation` services) — every process needs the exact same
# dependency set (app.jobs imports app.notifications' SmtpEmailProvider,
# app.services.approval_service, etc.), so a second image would only
# duplicate this one.

# Pinned to a digest (not just the floating `3.11-slim` tag) for
# reproducible builds — a rebuild next month gets the exact same base
# image, not whatever Debian/Python patch happens to be current that day.
# Pinned 2026-07-29; bump deliberately (`docker pull python:3.11-slim` +
# `docker inspect --format='{{index .RepoDigests 0}}' python:3.11-slim`)
# to pick up new base-image security patches.
FROM python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93 AS builder

WORKDIR /build

# Compilers only needed to build a couple of wheels (e.g. psycopg's
# non-binary transitive deps on some platforms); not present in the
# final image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt


# Same digest pin as the `builder` stage above.
FROM python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93 AS runtime

# Non-root user (fixed uid/gid so the same values work in Compose/K8s
# volume-permission configuration if ever needed).
RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --shell /usr/sbin/nologin --create-home appuser

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Application source, plus the Alembic config/migrations so an operator
# can run `docker run <image> alembic upgrade head` as a one-off
# migration step (docs/docker_deployment.md) without a separate image.
COPY app ./app
COPY alembic.ini ./alembic.ini

RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Liveness only (no dependency check) — matches
# app.api.routers.health's own liveness/readiness split: a container
# healthcheck restarting the process on a transient Supabase/Redis
# outage would not fix that outage and only churns the fleet.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health/live', timeout=3)" || exit 1

CMD ["uvicorn", "app.api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
