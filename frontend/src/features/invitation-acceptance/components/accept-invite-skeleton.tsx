import { Skeleton } from "@/components/ui/skeleton";

/** Shape-matches the loaded state (header + definition list + form) so
 * there is zero layout shift between the Suspense fallback, the
 * in-flight validate query, and the real content arriving — the same
 * "match the real geometry" rationale `DataTableSkeleton` already
 * applies to table views, applied here to a form-shaped page instead. */
export function AcceptInviteSkeleton() {
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Skeleton className="h-7 w-48" />
        <Skeleton className="h-4 w-64" />
      </div>
      <div className="space-y-2 rounded-lg border px-3 py-3">
        <Skeleton className="h-5 w-full" />
        <Skeleton className="h-5 w-full" />
        <Skeleton className="h-5 w-full" />
        <Skeleton className="h-5 w-full" />
        <Skeleton className="h-5 w-full" />
      </div>
      <div className="space-y-4">
        <Skeleton className="h-14 w-full" />
        <Skeleton className="h-14 w-full" />
        <Skeleton className="h-8 w-full" />
      </div>
    </div>
  );
}
