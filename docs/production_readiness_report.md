# Production Readiness Report

**Date:** 2026-07-26
**Scope:** A final production-polish pass across the whole platform (30 frontend
pages, ~156 components, 26 backend routers, 18 services, 20 repositories) —
visual consistency, animation, spacing, typography, loading/empty/error
states, accessibility, mobile responsiveness, keyboard navigation,
performance/bundle size, dead code, query optimization, and documentation.
Per the requesting instruction, **no redesign work was done** — every change
below is a fix, a consolidation, or a correction to something already built,
never a new visual direction.

## Summary

An initial audit (three parallel codebase passes, one per concern area)
found this codebase already unusually mature for a "final polish" request:
the shared component library, typography system, loading/error/empty-state
coverage, keyboard navigation, and code hygiene were already at or near bar.
Rather than making speculative changes across hundreds of files, this pass
fixed the small number of **concrete, verified defects** the audit actually
found, did one **bounded mechanical consistency pass** (toast messaging),
and corrected the one genuinely stale area (**architecture documentation**
still describing the pre-rewrite Streamlit stack). Everything else is
reported below as verified-already-at-bar, with the evidence, rather than
padded with unnecessary edits.

## What was fixed

### Correctness

1. **`frontend/src/app/(app)/requests/[id]/page.tsx`** — the Comments,
   Attachments, and Activity tabs branched only on `.isLoading`, never
   `.isError`. A failed fetch silently rendered as an empty list ("No
   comments yet.") instead of a genuine error, masking real failures. Fixed
   by adding an `isError` branch to each tab rendering the existing
   `ErrorState` with retry — the same pattern the page already used for its
   Workflow card.

2. **`app/services/workflow_definition_service.py`** — `_validate_assignees`
   looped over every `specific_user` stage assignee, calling
   `ProfileRepository.find_by_id` once per id (an N+1 query). Fixed by
   adding a batch `ProfileRepository.find_by_ids(ids)` (mirroring the
   existing `WorkflowRepository.list_by_ids` `.in_("id", [...])` precedent)
   and using it in place of the loop. Covered by the existing
   `test_workflow_definition_service.py` suite (all 15 tests still pass).

3. **`frontend/src/app/(app)/search/page.tsx`** — discovered while
   generating this report's bundle-size numbers: `next build` failed
   outright. The page calls `useSearchParams()` without a `<Suspense>`
   boundary, which Next.js requires for static prerendering ("missing
   suspense with CSR bailout"). Two other pages in this codebase
   (`requests/page.tsx`, `accept-invite/page.tsx`) already establish the
   fix pattern (split the page body into an inner component, wrap it in
   `<Suspense>` in the exported page function); `search/page.tsx` now
   follows the same pattern. **This means a production build of this app
   was already broken before this session** — worth flagging, since
   `PROJECT_SUMMARY.md` (an earlier session's snapshot) separately noted
   the frontend was never built in CI, which is exactly how this went
   undetected.

### Consistency

4. **Toast messaging** — `sonner`'s `toast.success`/`toast.error` was
   called directly in 24 files, most hand-rolling the same
   `error instanceof ApiError ? error.message : "fallback"` ternary. Added
   `frontend/src/lib/toast.ts` (`notifySuccess`, `notifyError`) and migrated
   every call site to it — purely mechanical, no message text or timing
   changed. Bare `catch { toast.error("static message") }` blocks (no bound
   error variable) were upgraded to `catch (error) { notifyError(error,
   "static message") }`, so a more specific `ApiError` message can surface
   instead of always showing the generic fallback — a deliberate, small UX
   improvement sanctioned by this same pass. Dynamic, non-exception toast
   messages (bulk-operation result summaries like `` `${succeeded}
   approved, ${failed} failed.` ``) were deliberately left as plain
   `toast.error(...)` calls, since there's no caught error to check.

5. **Typography** — `frontend/src/app/(app)/platform/companies/[id]/page.tsx`
   used a raw `<h1 className="text-xl font-bold">` for the company name
   instead of the shared `PageTitle` component every other entity-detail
   header uses (e.g. `request-detail-header.tsx`). Fixed to match. This was
   the *only* raw heading tag found outside `components/patterns/typography.tsx`
   in the entire `app/`+`features/` tree.

### Documentation

6. **8 stale architecture documents.** `docs/architecture.md`,
   `requirements.md`, `api_design.md`, `testing_strategy.md`,
   `design_philosophy.md`, `database_schema.md`, and `workflow_engine.md`
   still described the platform's original pre-rewrite baseline (a single
   Streamlit process, `src/ui`/`src/services`/`src/repositories`, Plotly
   charts) as current — only `docs/deployment.md` had been updated with a
   correction note after the actual FastAPI + Next.js rewrite. Added a
   matching "Superseded note" to the top of each of the other 7, stating
   plainly what's stale (the stack/file-path description) versus what's
   still accurate (the requirements substance, the layering philosophy,
   the schema, the workflow-engine design) — correcting the description in
   place rather than rewriting these formal design documents wholesale.
   `README.md`'s own Overview section had a smaller version of the same
   problem (described the app as "one deployable Python application" one
   paragraph below correctly describing it as FastAPI + Next.js) — fixed
   for internal consistency, and the Documentation Index now points out
   that some `/docs` files carry a superseded note.

## Verified already at bar (evidence, not just assertion)

- **Shared UI primitives** (`components/ui/*`, Base UI + CVA): `Button`,
  `Input`, `Select`, `Badge` all already have `focus-visible:ring-3`,
  `transition-*`, and disabled states; `Dialog`/`Select`/`Tooltip` already
  drive `animate-in`/`animate-out` off `data-open`/`data-closed` via
  `tw-animate-css`.
- **Typography system** (`components/patterns/typography.tsx`) is used
  almost everywhere — confirmed by grepping for every raw `<h1>`/`<h2>`/`<h3>`
  across `app/` and `features/` and finding exactly one bypass (fixed above).
- **Loading/empty/error state coverage**: 27 of 30 pages already use
  `Skeleton`/`ErrorState`/`EmptyState`; the other 3 are detail/settings
  pages with nothing that can legitimately be empty.
- **Mobile responsiveness**: grids already follow the correct mobile-first
  pattern (single column by default, `md:`/`xl:`/`lg:` expansion — e.g.
  `analytics/page.tsx`, `dashboard/page.tsx`), and `Table`/`DataTable`
  already wrap in `overflow-x-auto`. A real `MobileNavSheet` already
  provides the responsive nav.
- **Keyboard navigation**: a `cmdk` command palette (`Cmd/Ctrl+K`), a `?`
  keyboard-shortcuts dialog, and dedicated roving-tabindex hooks for
  approvals (j/k/a/x) and notifications already exist.
- **Bundle size / code-splitting**: chart-heavy panels (`recharts`) and the
  Workflow Designer canvas (`@xyflow/react`) were already behind
  `next/dynamic` before this pass.
- **Dead code / unused imports**: `ruff check app --select F` (backend)
  returns clean; no `.bak`/`*_old`/`*_copy` files, no `TODO`/`FIXME`/
  `console.log`/`debugger` anywhere in the frontend. The old Streamlit
  artifacts (`.streamlit/`, `app.py`, `app/auth/session_manager.py`) are
  already removed from the working tree (pending commit).
- **Database indexes**: repository filter columns (`requests.status`,
  `workflow_stages.assigned_to`/`assigned_role`, `audit_logs(company_id,
  action, created_at)`, `notifications(recipient_id, is_read)`, etc.) all
  have matching migration indexes; no gap found besides the N+1 fixed above.

## Verification performed

| Check | Result |
|---|---|
| `pytest tests/unit -q --no-cov` | **812 passed** |
| `ruff check .` (backend) | Clean |
| `mypy app` | Clean, 227 source files |
| `bandit -r app -ll -ii` | "No issues identified" (11 pre-existing Low/benign findings, unchanged) |
| `npx tsc --noEmit` (frontend) | Clean |
| `npx eslint .` (frontend) | Clean |
| `npx vitest run` (frontend) | **90/90 passed**, 15 test files |
| `npm run build` (frontend) | **Succeeds**, 31/31 routes generated (see below) |

### Bundle size (from `npm run build`)

| Route | Size | First Load JS |
|---|---|---|
| `/approvals` | 13.2 kB | **365 kB** (heaviest) |
| `/workflows/[requestType]/[version]` | 27.2 kB | 339 kB (xyflow canvas, already dynamic-imported) |
| `/admin/invitations` | 5.91 kB | 342 kB |
| `/platform/companies` | 7.08 kB | 341 kB |
| `/requests/[id]` | 10 kB | 336 kB |
| Shared by all routes | — | 103 kB |

Nothing here regressed from this session's changes (the toast-helper
migration and the two Suspense/error-state additions are functionally
inert on bundle size). `/platform`'s own 116 kB chunk size (before shared
JS) is the single largest individual route bundle and is worth a look in a
future pass — flagged in Technical Debt below rather than investigated
here, since it wasn't part of this session's findings and doing it justice
needs its own profiling pass.

### Testing limitation — disclosed, not glossed over

This is a CLI-only sandbox with no browser automation tool and no reachable
Supabase project or live FastAPI backend. I could run every build/lint/
type/test check above (all green), but I could **not** visually click
through pages in a real browser or literally resize a viewport to confirm
mobile layout, as the approved plan intended. A `next dev` + `curl` smoke
test was attempted as a partial substitute, but even that stalled — the
app's middleware calls out to Supabase for session validation on every
route, and with only a placeholder `NEXT_PUBLIC_SUPABASE_URL` configured
here, those calls hang rather than fail fast. Every route-rendering claim
in this report is backed by `next build`'s successful static generation of
31/31 routes (which does exercise each page's component tree at build
time) and by the existing Vitest component tests, not by an actual browser
session. Recommend a real click-through (desktop + 375px width) on
Dashboard, Requests, Analytics, Workflow Designer, and one Admin table page
before shipping, using a real or staging Supabase project.

## Remaining technical debt (explicitly out of scope for this pass)

Carried forward from this audit and an earlier session's `PROJECT_SUMMARY.md`
snapshot — each would be a behavioral/architectural change, not polish:

1. **Two parallel analytics stacks** (the narrow one feeding the personal
   dashboard vs. the rich `AnalyticsEngine` behind `/analytics`) — real,
   unreconciled duplication per the same prior snapshot.
2. **`Skeleton` has no size/shape presets** — every one of its ~48 call
   sites hand-rolls its own `className="h-X w-Y"`. A small, additive
   `variant` prop (e.g. `"text" | "avatar" | "card"`) would reduce
   duplication without changing any existing call site, but touching 48
   call sites to adopt it is a bigger, separate change than this pass's
   scope.
3. **`/platform`'s 116 kB own route bundle** (before the 103 kB shared
   chunk) is the largest individual route bundle in the app — worth
   profiling in a dedicated performance pass.
4. **`DEPLOYMENT_REPORT.md` and `PROJECT_SUMMARY.md`** at the repo root are
   dated, point-in-time generated snapshots (2026-07-25 and 2026-07-19
   respectively), not living documentation referenced from the README's
   Documentation Index. Left untouched as historical artifacts rather than
   edited in place; a future cleanup could archive them under `docs/history/`
   or delete them once their content is fully absorbed elsewhere.
