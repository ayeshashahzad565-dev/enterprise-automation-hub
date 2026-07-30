# Approval Workflow Recovery Strategy

## Why this document exists

`ApprovalService` (`app/services/approval_service.py`) performs several
independent writes per decision. The Supabase client this project uses
gives no cross-statement `BEGIN`/`COMMIT` — each repository call commits
(or fails) on its own. Before this pass, `_decide_stage` opened a
`TransactionContext` but registered zero compensations: if the stage
decision succeeded and a later write failed, the request was left
permanently, silently half-advanced (a stage marked `approved` with no
matching request-level effect, or a newly created stage the request never
points to). This document describes the fix: what every write does, what
undoes it (or why nothing can), how retries are made safe, and the one
inherent limitation that remains, disclosed rather than hidden.

## Every write, and its compensation

| # | Write | Compensation | Registered by |
|---|---|---|---|
| 1 | `approval_repo.approve_stage()` / `reject_stage()` — decides the stage | `approval_repo.revert_to_pending()` — clears `status`/`decided_by`/`decided_at`/`decision_note` back to a genuine pre-decision state | `_decide_stage` |
| 2 | *(approval, non-terminal)* `workflow_stage_repo.create_stage()` — inserts the next stage | `workflow_stage_repo.delete_if_unchanged()` — version-guarded hard delete | `_advance_after_approval` |
| 3 | `request_repo.set_current_stage()` — advances/terminates the request | `request_repo.set_current_stage()` again, with the request's captured pre-decision snapshot | `_advance_after_approval` / `_finalize_rejection` |
| 4 | `audit_repo.record_event()` — the audit trail entry | none — see below | `_decide_stage` |
| 5 | `notification_service.notify_*()` | none — deliberately outside the integrity boundary, see below | `_decide_stage` |

`escalate_stage` has the same shape at smaller scale: (1)
`approval_repo.escalate_stage()` reassigns the stage — compensated by
calling `escalate_stage()` again with the pre-escalation
`assigned_to`/`assigned_role`; (2) `audit_repo.record_event()` — no
compensation, same reasoning as above; (3)
`notification_service.notify_escalation()` — outside the boundary, same
reasoning as above.

Every compensation is registered **immediately after** its forward write
succeeds, pinned to the version that write just returned — so it only
ever fires if a *later* step fails, and only ever touches a row that
genuinely hasn't been touched by anything else since. `TransactionContext`
(`app/services/workflow_definition_service.py:63`) runs every registered
compensation in reverse order the moment any later step raises, logging
(never re-raising) a compensation that itself fails, so one failed
rollback step never prevents the rest of the rollback from running.

**Why the audit write (step 4) is never compensated.** An `INSERT` either
lands or it doesn't — there is nothing to undo for the one step whose own
failure is what triggers every earlier compensation to run. `audit_logs`
also has no `UPDATE`/`DELETE` grant at all, by design (immutability), so a
"delete the audit row" compensation isn't merely unnecessary here, it
would be impossible even if it were.

**Why `completed_at` needed a small repository fix to be revertible.**
`RequestRepository.set_current_stage()` used to only include
`completed_at` in its update payload when a non-`None` value was passed —
meaning a compensating call couldn't put it back to `None` after a
terminal (`COMPLETED`/`REJECTED`) transition; the field would stay set. It
now always writes `completed_at` explicitly (including `None`). Every
existing forward call site that omits the argument does so on a row where
the column is already `None`, so this is a no-op for all of them — it
exists purely so a rollback can put it back.

## Idempotency and duplicate prevention

Three separate mechanisms combine to make this "prevent duplicate
approvals, ensure retries are safe":

1. **Optimistic locking already serializes concurrent decisions.** Two
   callers racing to decide the same stage can't both win —
   `update_with_optimistic_lock`'s `WHERE id = :id AND version =
   :expected` means only one write matches; the other gets
   `ConcurrentUpdateError`. This was already true before this pass.
2. **Full compensation coverage means a failed decision always unwinds to
   a genuine `pending` stage.** Before this pass, a decision that failed
   partway through left the stage `approved`/`rejected` with an
   inconsistent request — a retry of that stage would hit a confusing,
   generic authorization error ("stage not pending"), and there was no
   guarantee the request was in a coherent state either. Now, any failure
   anywhere in the sequence puts the stage (and the request, and any
   created stage) back exactly as they were — so a retry after a failure
   is always a fresh, safe, correct attempt, never a second application of
   a half-applied one.
3. **A retry of an already-*fully-committed* decision by the same actor
   now replays idempotently.** `_decide_stage` checks, immediately after
   fetching the stage and before authorization: if the stage is already
   decided to exactly the requested target status by exactly this caller,
   return the outcome reconstructed from current state instead of
   re-running authorization, the state-machine check, or any write. This
   is what makes a genuine "client resubmitted because the original
   response was lost, but the write actually succeeded" retry return a
   clean success instead of the same confusing "stage not pending" error
   — without it, a caller has no safe way to retry a decision whose result
   they never saw. A different actor, or a different target status
   (approving a stage you already rejected), is a genuine conflict and is
   still rejected exactly as before — the replay check requires both an
   exact status match and an exact actor match.

**A note on `expected_version` and retries.** Optimistic-lock semantics
mean a caller who pins a specific `expected_version` from an earlier read
and retries after a rollback-and-retry cycle may see a fresh concurrency
conflict if the version moved since — this is the *correct* behavior of
optimistic concurrency (state changed since you last observed it, go
re-fetch), not a bug to work around. A caller who omits `expected_version`
(the default, and what every UI actually does) always re-fetches the
current version at the top of each call and is unaffected either way.

## Notifications are outside the integrity boundary, deliberately

`_dispatch_post_decision_notifications` (and `escalate_stage`'s
`notify_escalation`) run *after* the `TransactionContext` block closes,
wrapped in a `try`/`except` that logs and swallows. By the time a
notification is attempted, the actual decision has already durably
committed — a transient notification failure (an email-service hiccup, a
dropped connection to the notifications table) must never turn an
already-successful decision into an API-level error for the caller, and
must never trigger a rollback of a decision that already correctly landed.
This is the same "a best-effort side effect must not mask the primary
outcome" precedent `TransactionContext.__exit__` already applies to a
failed compensation.

## The one known, accepted limitation

`workflow_stages` has no soft-delete column, so
`WorkflowStageRepository.delete_if_unchanged`'s compensation for a
just-created stage (write #2 above) is a genuine `DELETE`, version-guarded
against the exact version the row had immediately after creation. In the
narrow window between that creation and the later failure that triggers
rollback, another actor could in principle race in and decide that
brand-new stage before the rollback runs — its version would no longer
match, the guarded delete becomes a safe no-op (never destroying a real
decision), and this is logged as a warning. In that specific, rare race,
the original triggering decision is still correctly rolled back, but the
stage that raced ahead is left in place, decided, no longer pointed to by
the request's `current_stage_id`. This is an inherent limitation of
compensation-based orchestration without true database transactions — the
same category of limitation `TransactionContext` itself already documents
candidly — not a gap this pass silently ignored. Closing it fully would
require either a genuine DB transaction (not available on this stack) or
row-level locking PostgREST doesn't expose to this application.

## Verification

`tests/unit/test_approval_service.py`'s `TestCompensationOnPartialFailure`
and `TestNotificationFailureIsolation` classes cover: audit failure after
a completing approval, after a multi-stage (non-terminal) approval, and
after a rejection; a failure at stage creation; a failure at request
advancement; the same audit-failure case for `escalate_stage`; and a
notification failure that must not surface as an API error or affect the
already-committed decision. Each asserts the resulting state directly
(the stage's exact fields, the request's exact fields, any created stage)
rather than only that an exception was raised. `TestAuthorizationAndValidation`
covers the idempotent-replay path and both of its negative cases (a
different actor, and the same actor requesting a different status).
