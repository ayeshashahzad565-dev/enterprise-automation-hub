# Scheduler Distributed Coordination

## Why this document exists

`SchedulerCoordinator` (`app/scheduler/scheduler.py`) originally prevented
overlapping execution of a job with nothing more than a per-job
`threading.Lock` — correct for one process, meaningless across more than
one. Multi-instance safety was, until this pass, not a lock at all: a
static `SCHEDULER_LEADER` environment variable manually designated exactly
one instance at deploy time, and if that instance crashed, every scheduled
job (Escalation Check, Reminder Dispatch, the Stuck Job Reaper) simply
stopped running until an operator noticed and manually reassigned
leadership on a different instance (the old `docs/deployment.md` Section
13.2–13.4). This document describes the fix: a real, Redis-backed,
self-healing coordination layer, and exactly what still degrades to the
old static behavior when Redis is not configured.

## The two Redis primitives

Both are built on one abstraction, `app.scheduler.distributed_lock.
DistributedLock`, backed by `redis.lock.Lock` — redis-py's own correct,
token-fenced, Lua-scripted distributed lock (`SET NX PX` to acquire; a
Lua script checking token ownership before `PEXPIRE`/`DEL` for
extend/release). Nothing here hand-rolls locking logic; the primitive
this codebase already depends on (`redis>=5.0`) provides it.

### 1. Leader election (`eah:scheduler:leader`)

`app.scheduler.leader_election.LeaderElection` runs a background thread on
every instance that has opted into the Scheduler pool
(`SCHEDULER_LEADER=true` — see below), continuously attempting to acquire
this one shared lock, or renew it if already held. Renewal happens every
`ttl_seconds / 3` (so three renewal attempts fit inside one TTL window
before ordinary scheduling jitter alone could cause a spurious loss), reset
to a full `SCHEDULER_LEADER_LOCK_TTL_SECONDS` (default 30s) each time.

- **A crashed leader** simply stops renewing. Its lock expires on its own
  within one TTL window, and another participating instance's next tick
  (at most `ttl_seconds / 3` later) acquires it — automatic failover, no
  manual step.
- **A gracefully shut-down leader** (`LeaderElection.stop()`, called from
  `app.bootstrap.shutdown_scheduler`) releases the lock explicitly, so a
  normal deploy/restart hands off leadership immediately instead of making
  every other instance wait out the full TTL.
- **Fail-safe direction**: any Redis error during acquire/extend is
  treated as "not leader," never as "assume still leader" (see
  `LeaderElection._tick`'s docstring). This is what prevents a Redis
  outage from producing two simultaneous leaders once connectivity
  recovers — an instance that cannot confirm it still holds the lock
  always assumes it does not.

### 2. Per-job execution lock (`eah:scheduler:job-lock:{job_name}`)

One lock per registered job, acquired non-blocking by
`SchedulerCoordinator._make_runner` immediately before a job's body runs,
released in `finally`. This is defense-in-depth *independent* of leader
election's own correctness: even in a theoretical split-brain window — a
former leader's renewal is delayed past its TTL at the exact moment a new
leader is elected — only one instance can actually hold this lock and run
the job at any instant. Leader election answers "who *should* run this
job"; this lock answers "who *is* running this job right now," and only
the second question is what actually prevents a duplicate execution.

TTL (`SCHEDULER_JOB_LOCK_TTL_SECONDS`, default 300s) is this lock's own
crash-recovery backstop: an instance that crashes mid-job stops renewing
nothing (this lock is not renewed mid-execution, unlike the leader lock —
see the accepted limitation below), and the lock simply expires after the
configured TTL, letting another instance's subsequent tick proceed.

## `SCHEDULER_LEADER`'s meaning changed: pool membership, not "the leader"

Before this pass, `SCHEDULER_LEADER=true` meant "this specific instance is
the Scheduler." After this pass, it means "this instance participates in
the Scheduler pool at all" — registers its jobs, and, when Redis is
configured, contends for live leadership:

- **Without `REDIS_URL` configured**: unchanged from before this pass.
  Exactly one participating instance per environment must set this to
  `true`; that instance always executes every tick (the in-process lock
  is the only overlap protection, since `NullDistributedLock` never
  actually contends with anything and `leader_check` is never even
  wired in — see `app.bootstrap.build_application_resources`). This is
  still a manual, operator-enforced discipline, not something a single
  process's own configuration can verify.
- **With `REDIS_URL` configured**: more than one instance may set this to
  `true` safely — in fact this is the expected production topology (see
  `docker-compose.production.yml`'s `backend`/`backend-2`). All of them
  register jobs and run `LeaderElection`; only the one holding
  `eah:scheduler:leader` at any moment actually executes ticks (every
  other participating instance's `leader_check` returns `False`, and
  `SchedulerCoordinator` skips the tick outright, counted in
  `JobStatistics.skipped_not_leader_count`, without even attempting the
  in-process lock).

`app.jobs.worker` processes must always leave `SCHEDULER_LEADER=false`,
regardless of whether Redis is configured — they consume the job queue,
not the Scheduler, and were never meant to register scheduled jobs or
contend for this lock. This exclusion is unconditional in
`app.bootstrap.build_application_resources`: `LeaderElection` is
constructed and started, and `SchedulerCoordinator.register_job` is ever
called, only when `settings.scheduler.is_leader` is `true` — Redis
configuration alone does not enroll a process.

## What a tick actually checks, in order

`SchedulerCoordinator._make_runner`'s `_run()`, per job, on every trigger:

1. **`leader_check()`** (if configured): is this instance currently the
   elected leader? If not, skip immediately —
   `skipped_not_leader_count += 1`. Cheapest check, no Redis round trip
   beyond what `LeaderElection`'s own background thread already does.
2. **The in-process `threading.Lock`** (unchanged from before this pass):
   is a previous tick of *this same job, in this same process* still
   running? If so, skip — `skipped_overlap_count += 1`.
3. **The per-job `DistributedLock`**: does another instance currently hold
   this job's execution lock? If so, skip —
   `skipped_distributed_lock_count += 1`. This is the check that actually
   prevents a genuine cross-instance duplicate execution; the first two
   only prevent it in the common case.
4. Run the job body; release the distributed lock, then the in-process
   lock, in `finally`, regardless of outcome.

Every one of these is optional and defaults to today's original,
single-instance behavior: `leader_check=None` means always-leader;
`distributed_lock_factory=None` means every job's distributed lock is a
`NullDistributedLock` that always "acquires." Constructing a
`SchedulerCoordinator` exactly as before this pass (no new keyword
arguments) is unaffected.

## Safe retries and duplicate-job prevention are the same story

Escalation Check and Reminder Dispatch already re-evaluate durable
Postgres state fresh on every run (WEDD Section 8.6, unaffected by this
change) — a missed or re-run tick after a crash simply finds whatever
overdue stages currently exist, not a stale in-memory queue. Their
downstream writes are already guarded by optimistic locking
(`ApprovalRepository.escalate_stage`). This pass does not add new
idempotency logic to the jobs themselves; it only guarantees that at most
one instance is *attempting* a given tick at any moment, which is the
piece that was previously missing. Combined, this is what "prevents
duplicate job execution" end-to-end: leader election plus the per-job
lock stop two instances from racing to enqueue the same escalation/
reminder work in the first place, and the pre-existing optimistic locking
one layer down means even a genuine race that slips through both locks
(the disclosed limitation below) cannot corrupt state — only, at worst,
attempt redundant work that the second attempt's own optimistic-lock
check would reject.

## Health/readiness reporting

`GET /health` and `/health/ready` (`app.api.routers.health`) report two
fields:

- `scheduler_active`: with Redis-backed election active, this is
  `resources.leader_election.is_leader` — this instance's own live belief
  about whether it is currently the leader, fail-safe toward `False`.
  Without Redis, it falls back to `resources.scheduler_stats is not
  None` (today's original meaning: "did this instance register
  anything"). The deployment-time verification this document's
  predecessor described — confirm exactly one instance in the fleet
  reports `true` — still holds under either mode; under Redis-backed
  election it is now self-correcting rather than a one-time snapshot.
- `scheduler_leader_election`: `"redis"` or `"static"`, so which mode is
  active is never ambiguous from the response alone.

## The one accepted, disclosed limitation

The per-job distributed lock is **not renewed mid-execution** — it is
acquired once, held for the job's actual runtime, and released when the
job finishes (or expires via its TTL if the instance crashes first). If a
job somehow runs *longer* than `SCHEDULER_JOB_LOCK_TTL_SECONDS` (default
300s — chosen comfortably above the discovery-and-enqueue work Escalation
Check/Reminder Dispatch actually perform), the lock could expire while the
job is still genuinely running, and — only in the additional, narrow case
that leader election has also (incorrectly) elected a second leader at
that exact moment — a second instance could begin the same job
concurrently. This is the same category of inherent limitation
compensation-based systems in this codebase already disclose candidly
(see `docs/approval_recovery_strategy.md`'s own accepted race window) —
not a gap silently ignored. The operational mitigation is straightforward:
set `SCHEDULER_JOB_LOCK_TTL_SECONDS` comfortably above the slowest
realistic execution time for every registered job in your deployment, the
same discipline any lock-based mutual exclusion system requires.

## Verification

- `tests/unit/test_scheduler_distributed_lock.py` — `RedisDistributedLock`
  against `fakeredis.FakeRedis`: acquire/release/extend/owned, a second
  contender failing to acquire while held, TTL expiry letting a second
  contender succeed, and `NullDistributedLock`'s always-succeeds contract.
- `tests/unit/test_scheduler_leader_election.py` — `LeaderElection`
  against `fakeredis.FakeRedis` shared across instances: exactly one of
  two concurrently-started elections wins, a graceful `stop()` hands off
  leadership immediately, and a "crashed" (never-stopped, never-renewed)
  leader's claim is picked up by another instance once its TTL expires.
- `tests/unit/test_scheduler_coordinator.py` — `leader_check` skipping a
  tick and incrementing `skipped_not_leader_count`; a `distributed_lock_
  factory`-provided lock already held by another simulated instance
  skipping a tick and incrementing `skipped_distributed_lock_count`.
- `tests/integration/test_scheduler_multi_instance_safety.py` — the
  end-to-end proof: two independent `SchedulerCoordinator` +
  `LeaderElection` pairs sharing one `fakeredis.FakeRedis` (simulating two
  backend containers against one real Redis), driven by real
  `threading.Thread`s, proving leader-election correctness, mutual
  exclusion even under a simulated split-brain window, and automatic
  crash recovery.
