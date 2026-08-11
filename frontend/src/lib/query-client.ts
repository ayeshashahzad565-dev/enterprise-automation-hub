import { QueryClient } from "@tanstack/react-query";

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Tuned for perceived speed on navigation. Every request to this
        // API costs a real round trip to a remote Supabase region
        // (~240ms floor), so the difference between "served from cache"
        // and "refetched" is the difference between a page appearing
        // instantly and visibly hitching on every visit.
        //
        // staleTime: data stays fresh for 5 minutes, so navigating back
        // to a page already visited renders immediately from cache with
        // no request at all. Approvals/requests here change on human
        // timescales (someone approving a request), not continuously, so
        // this is not stale enough to mislead — and any mutation
        // invalidates its own keys explicitly, which bypasses this
        // entirely and refetches at once.
        staleTime: 5 * 60 * 1000,
        // gcTime > staleTime by a wide margin: keeps the cached page
        // around long enough that going Dashboard -> Requests -> back to
        // Dashboard still hits cache rather than a cold refetch.
        gcTime: 30 * 60 * 1000,
        // Default is true, which refires every active query whenever the
        // user alt-tabs back to the browser — on this API that means a
        // burst of round trips and a UI that stutters for no reason the
        // user asked for. staleTime already governs genuine freshness.
        refetchOnWindowFocus: false,
        // Same reasoning for remounts: a component remounting inside a
        // still-fresh window should paint from cache, not refetch.
        refetchOnMount: false,
        retry: 1,
      },
    },
  });
}
