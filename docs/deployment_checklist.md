# Production Deployment Checklist

Companion to `docs/docker_deployment.md` (command-level Docker/Compose
operations) and `docs/deployment.md` (architectural rationale). This
document is the practical, one-pass checklist for taking a specific commit
to production, plus a record of the CI/CD hardening pass that produced it
(2026-07-29).

## 1. What changed in this pass

| Area | Before | After |
|---|---|---|
| `pyproject.toml` vs `requirements.txt` | Same 9 packages, different version bounds (unbounded vs `<N.0`) | Identical bounds in both — `pyproject.toml` is the single hand-edited source |
| Lockfiles | None — every install re-resolved loose ranges | `requirements.txt` (production) and `requirements-dev.txt` (dev/test/CI) both exact-pinned; `scripts/check_lockfile_sync.py` fails CI if a pin ever stops satisfying `pyproject.toml`'s declared range |
| Unused dependencies | `black` (no invoker anywhere — `ruff` is this repo's actual formatter/linter) and `httpx2` (unrelated experimental package, zero imports) in `pyproject.toml`'s `dev` extra; `shadcn` (a scaffolding CLI) listed as a frontend runtime dependency | All three removed/reclassified (`shadcn` moved to `devDependencies`) |
| CI (`ci.yml`) | Installed via `pip install -e ".[dev]"` (floating), no pip cache | Installs the pinned `requirements-dev.txt`; pip cache enabled; new "Verify lockfiles are up to date" step |
| Security (`security.yml`) | `pip-audit` scanned `pip install -e .` (loose, freshly-resolved); `npm audit` was fully non-blocking (`continue-on-error: true` at every severity); no container image scanning at all | `pip-audit` scans the exact pinned `requirements.txt`; `npm audit --audit-level=critical` is now blocking (passes today — 0 criticals); new `container-scan` job (Trivy) fails the build on `CRITICAL` image vulnerabilities for both the backend and frontend images |
| Dockerfiles | `FROM python:3.11-slim` / `FROM node:20-slim` — floating tags | Pinned to digest (`python:3.11-slim@sha256:db3ff2e...`, `node:20-slim@sha256:2cf067c...`) — a rebuild next month gets the identical base image |

## 2. Pre-deploy checklist

- [ ] **`APP_ENVIRONMENT=production` (or `staging`) is set explicitly.** This is the master switch every other hardening check below depends on (`Environment.requires_production_grade_hardening`) — it defaults to `development` if unset, with no runtime cross-check that this was intentional. Forgetting this one variable silently disables every check in this list: CORS falls back to `localhost:3000`, SMTP becomes optional, `APP_BASE_URL` falls back to `localhost:3000` (breaking every invitation email link), and interactive API docs stay enabled. Verify with `curl <host>/api/v1/health` and confirm `/api/docs` returns `404`, not a Swagger UI.
- [ ] `alembic upgrade head` applied against the target environment's database **before** new application code starts serving traffic (never as an implicit container-startup side effect — see `docs/docker_deployment.md` §6).
- [ ] `.env` (backend) and `frontend/.env.local` populated with the target environment's real Supabase project credentials — never point at a shared staging/production project from a developer machine.
- [ ] `REDIS_URL` set if shared rate limiting / shared analytics cache / the queued email worker are wanted for this environment; every one of those features degrades to its single-process default when unset (no hard Redis requirement).
- [ ] CI green on the target commit: lint (ruff), type-check (mypy), unit/integration tests, both security workflows, both Docker builds.
- [ ] `docker compose -f docker-compose.production.yml config` validates (confirms env-var interpolation resolves; run this after populating `.env`, not before).
- [ ] GHCR image tag to deploy identified (`cd.yml` tags every push to `main` as `latest` plus the commit SHA — prefer pinning the deploy to the SHA tag, not `latest`, for an auditable rollback point).

## 3. CI/CD gates now in place (fail-closed)

| Gate | Blocks on | Workflow |
|---|---|---|
| Lint / type-check / unit tests | Any failure | `ci.yml` |
| Lockfile sync | A pin no longer satisfying `pyproject.toml` | `ci.yml` |
| Python dependency audit (`pip-audit`) | Any known vulnerability (stricter than critical-only) | `security.yml` |
| Frontend dependency audit (`npm audit`) | `critical` severity (high/moderate remain informational — see below) | `security.yml` |
| Secret scan (`gitleaks`) | Any committed secret | `security.yml` |
| Static analysis (`bandit -ll -ii`) | Medium+ severity, medium+ confidence | `security.yml` |
| Container image scan (Trivy) | `CRITICAL` severity with an available fix, both images | `security.yml` |
| Frontend build | Any `next build` failure | `ci.yml` |

## 4. Known, disclosed, accepted gaps

- **12 high / 2 moderate frontend npm advisories are not blocking.** The only fix (`npm audit fix --force`) downgrades `next` to a 2019-era 9.x release — clearly wrong for an app on Next.js 15. Tracked, re-checked on every build; revisit once upstream ships a real fix.
- **Hash-pinning (`--generate-hashes`) was not completed.** `requirements.txt`/`requirements-dev.txt` are exact-version-pinned (fully reproducible: the same versions install every time) but not SHA256-hash-verified, because generating hashes requires resolving/downloading each package under the exact target platform (`python:3.11-slim`, Linux/cp311) and the sandboxed environment this pass was done in had persistent, unresolvable PyPI network failures (DNS resolution failures, read timeouts, truncated downloads) inside every container attempted. The committed lockfiles were instead built by extracting the actual, previously-verified-working dependency closure from an already-built `enterprise-automation-hub-backend` image (`pip freeze` inside the running container) — a real, working resolution, just not hash-verified. **Recommended follow-up**: run `pip-compile --generate-hashes` for both lockfiles from an environment with reliable network access (any normal CI runner or developer machine) and commit the result; `scripts/check_lockfile_sync.py` will not object as long as the versions still satisfy `pyproject.toml`.
- **A live, from-scratch `docker build --no-cache` was not completed in this pass.** The same sandbox's Docker daemon became unresponsive (network-related resource exhaustion) partway through verification. Confidence in the Dockerfile changes instead comes from: the digest-pinned base image was already pulled and inspected directly (`db3ff2e1...`, `2cf067cf...`); `docker compose config` validated both Compose files cleanly; and the new `requirements.txt` pins are exactly what an already-built, previously-working image has installed (`pip freeze` inside it matches line-for-line). **Recommended follow-up**: run `docker build --no-cache -f Dockerfile .` and the frontend equivalent once, on any machine with stable network, before merging.
- ~~Two pre-existing, unrelated test failures~~ — **`test_tenant_scoping_enforcement.py`'s failure is resolved**: its route-introspection traversal was repaired in a later pass to flatten FastAPI's `_IncludedRouter` wrappers correctly (via `fastapi.routing.iter_route_contexts`), verified with a real red/green cycle; see that test file's own module docstring for the full explanation. `tests/unit/test_metrics_endpoint.py::test_a_request_increments_the_request_count_metric` is **not** resolved, but is subtler than originally described: it passes when the full `pytest -m unit` suite runs (902/902 passing, confirmed during this hardening pass), but fails in isolation (`pytest tests/unit/test_metrics_endpoint.py`) — some other test elsewhere in the full suite leaves process-global state (almost certainly the `prometheus_client` default registry, which is module-level and shared across the whole pytest process) that this test's assertion depends on without setting up itself. A real, order-dependent test-isolation bug, not a route-representation issue; still a disclosed, open gap, recommended as a follow-up (make the test construct/assert against its own isolated `CollectorRegistry` rather than the global default one).
- **Dependabot/Renovate was not configured.** Not part of the requested task list; the lockfile-sync check (`ci.yml`) catches drift whenever a human bumps `pyproject.toml`, but nothing currently opens that bump automatically. Recommended as a natural next step.

## 5. Rollback

- `cd.yml` tags every image with the commit SHA (`type=sha,format=long`) in addition to `latest` — redeploying a prior SHA tag is the rollback path; no image is ever overwritten.
- Migrations in this codebase are forward-only in production philosophy (`docs/deployment.md` §11) — a schema rollback is a new forward migration, not `alembic downgrade`, on any environment with real data.

## 6. What changed in the 2026-07-30 hardening pass

| Area | Before | After |
|---|---|---|
| `GRAFANA_ADMIN_PASSWORD` | `docker-compose.production.yml` fell back to Grafana's well-known `admin` default if unset | No fallback (`${GRAFANA_ADMIN_PASSWORD:?...}`) — `docker compose up` refuses to start without it |
| `CORS_ALLOWED_ORIGINS` | Required in Staging/Production, but `*` was accepted | `*` is now rejected in every environment — this API is called with `allow_credentials=True`, so a wildcard origin would let any site make credentialed requests |
| `APP_BASE_URL` | No environment gate; unset in Staging/Production silently pointed every invitation email link at `localhost:3000` | Required in Staging/Production, matching `CORS_ALLOWED_ORIGINS`/SMTP's existing discipline |
| Composite indexes | `requests`/`workflow_stages`/`audit_logs` company-scoped composites existed (`0012`, `0013`, `0021`); `profiles`, `requests.requester_id`, `audit_logs.actor_id`, and `user_invitations` did not | Added `profiles (company_id, role, department)`, `requests (company_id, requester_id)`, `audit_logs (company_id, actor_id, created_at desc)`, `user_invitations (company_id, status, expires_at)` (migrations `0023`, `0024`) |
| CI workflow permissions | `ci.yml`/`security.yml`/`e2e.yml`/`integration.yml` had no explicit `permissions:` block | All four now declare `permissions: contents: read`, matching `cd.yml`'s existing least-privilege precedent |
| Stale documentation | README's "Future Enhancements" listed dynamic scheduler leader election and containerized deployment as *future* work (both had shipped); WEDD Section 20.6 described distributed workflow execution as purely hypothetical; `docs/deployment.md` referenced a "Nightly Analytics Aggregation" scheduled job that was never implemented; `CONTRIBUTING.md` linked to the nonexistent `docs/ADD.md` | All corrected; `SchedulerSettings.analytics_interval_hours` (`app/config/settings.py`) and `.env.example` now clearly mark that setting as reserved/unused rather than implying a job consumes it |
| Prometheus/Grafana port exposure | Documented as "put behind a load balancer," with no callout that Docker's `iptables` manipulation can bypass a host firewall rule that appears to block ports 9090/3001 | `docs/docker_deployment.md` now calls this out explicitly, recommending cloud security-group/network-ACL restriction |

See `docs/database_schema.md` §10.2 for the full index table (including what was deliberately *not* added and why) and `tests/unit/test_api_docs_gating.py`/`tests/unit/test_invitation_settings.py` for the new regression tests covering the CORS/`APP_BASE_URL` fixes.
