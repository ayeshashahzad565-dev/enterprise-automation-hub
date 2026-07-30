import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

import { supabaseAnonKey, supabaseUrl } from "@/lib/supabase/env";

/**
 * Creates a Supabase client for use in Server Components / Route Handlers.
 *
 * Writing cookies from a Server Component itself is a no-op in Next.js (it
 * throws only if uncaught) — session refresh in that context is handled by
 * `middleware.ts` instead, which runs before the Server Component and can
 * write response cookies.
 */
export async function createClient() {
  const cookieStore = await cookies();

  return createServerClient(supabaseUrl, supabaseAnonKey, {
    cookies: {
      getAll() {
        return cookieStore.getAll();
      },
      setAll(cookiesToSet) {
        try {
          for (const { name, value, options } of cookiesToSet) {
            cookieStore.set(name, value, options);
          }
        } catch {
          // Called from a Server Component with no request/response to
          // attach cookies to — safe to ignore, since middleware.ts already
          // refreshes and persists the session on every navigation.
        }
      },
    },
  });
}
