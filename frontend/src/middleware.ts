import type { NextRequest } from "next/server";

import { updateSession } from "@/lib/supabase/middleware";

export async function middleware(request: NextRequest) {
  return updateSession(request);
}

export const config = {
  matcher: [
    /*
     * Match all request paths except:
     * - _next/static, _next/image (Next.js internals)
     * - static asset files (svg, png, jpg, jpeg, gif, webp, ico)
     * - api/ (Next.js Route Handlers, e.g. the container-healthcheck-only
     *   GET /api/health — these are not authenticated pages, so session
     *   refresh/redirect enforcement does not apply to them)
     */
    "/((?!_next/static|_next/image|api/|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)",
  ],
};
