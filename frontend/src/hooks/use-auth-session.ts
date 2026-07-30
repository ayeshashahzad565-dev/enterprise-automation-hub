"use client";

import { useEffect, useState } from "react";
import type { AuthChangeEvent, Session, User } from "@supabase/supabase-js";

import { shouldEndUnrememberedSession } from "@/features/auth/remember-me";
import { createClient } from "@/lib/supabase/client";

export interface AuthSessionState {
  user: User | null;
  session: Session | null;
  loading: boolean;
}

/**
 * Subscribes to the browser Supabase client's own session state, which it
 * keeps fresh via its internal auto-refresh timer — no polling or manual
 * refresh logic is implemented here.
 */
export function useAuthSession(): AuthSessionState {
  const [state, setState] = useState<AuthSessionState>({
    user: null,
    session: null,
    loading: true,
  });

  useEffect(() => {
    const supabase = createClient();
    let cancelled = false;

    (async () => {
      // Supabase's session cookie is always long-lived (see remember-me.ts);
      // "remember me" is honored here instead, by ending the session the
      // first time it's observed in a genuinely new browser session.
      if (shouldEndUnrememberedSession()) {
        await supabase.auth.signOut();
      }

      const {
        data: { session },
      } = await supabase.auth.getSession();
      if (!cancelled) setState({ user: session?.user ?? null, session, loading: false });
    })();

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event: AuthChangeEvent, session: Session | null) => {
      if (!cancelled) setState({ user: session?.user ?? null, session, loading: false });
    });

    return () => {
      cancelled = true;
      subscription.unsubscribe();
    };
  }, []);

  return state;
}
