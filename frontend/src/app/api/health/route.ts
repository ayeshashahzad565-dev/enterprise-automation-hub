import { NextResponse } from "next/server";

/**
 * Container-healthcheck-only endpoint (frontend/Dockerfile's HEALTHCHECK).
 *
 * Deliberately dependency-free: it reports only that the Next.js server
 * itself is up, never contacting Supabase or the backend API — matching
 * the backend's own `GET /api/v1/health/live` liveness semantics (see
 * `app/api/routers/health.py`), not its readiness check. Excluded from
 * `src/middleware.ts`'s session-refresh/route-protection matcher, so this
 * never redirects to `/login` for an unauthenticated healthcheck caller.
 */
export function GET() {
  return NextResponse.json({ status: "ok" });
}
